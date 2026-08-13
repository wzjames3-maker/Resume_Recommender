import enum
import hashlib
import re
from dataclasses import dataclass, field

from app.services.model_client import ModelCallError
from app.services.resume.pii import (
    PIIMappingEntry,
    desensitize_text,
    restore_pii_values,
)
from app.services.resume.schema import (
    KNOWN_FIELDS,
    RESUME_SCHEMA_VERSION,
    SchemaValidationError,
    validate_candidate_json,
)

RESUME_PROMPT_VERSION = "prompt/v1"

# 阶段一（结构识别）：A-1 裁决 P2 默认走单次调用（extract_candidate），
# 本接口保留供评测分类别 F1 不达标时启用两阶段。
STRUCTURE_SYSTEM_PROMPT = (
    "你是简历结构识别器。给定简历 Markdown，输出 JSON: {\"sections\": [...]}，"
    "每个 section 含 title 与 block_id 列表。"
)


class FailureClass(str, enum.Enum):
    not_retryable = "not_retryable"
    retryable = "retryable"


def classify_failure(exc: Exception) -> FailureClass:
    if isinstance(exc, SchemaValidationError):
        return FailureClass.not_retryable
    if isinstance(exc, ModelCallError):
        return FailureClass.retryable if exc.retryable else FailureClass.not_retryable
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return FailureClass.retryable
    text = str(exc).lower()
    if any(k in text for k in ("timeout", "429", "rate limit", "temporarily", "503", "502")):
        return FailureClass.retryable
    return FailureClass.not_retryable


@dataclass
class StructuredResult:
    candidate: dict
    evidence: dict = field(default_factory=dict)
    pii_mapping: list[PIIMappingEntry] = field(default_factory=list)


async def detect_structure(llm, ir: str) -> list:
    """阶段一（结构识别）保留接口（A-1）：评测分类别 F1 不达标时启用两阶段。"""
    masked_ir, _ = desensitize_text(ir)
    raw = await llm.chat_json(STRUCTURE_SYSTEM_PROMPT, f"<resume>\n{masked_ir}\n</resume>", {})
    return raw.get("sections") or []


EXTRACT_SYSTEM_PROMPT = f"""你是简历信息抽取器。输入简历 Markdown IR（PII 已替换为 PII:* token），输出严格 JSON（schema_version={RESUME_SCHEMA_VERSION}）。

规则：
1. 字段无法从简历确定时标 null，禁止编造。
2. 仅输出以下字段，不得输出未知字段: {', '.join(sorted(KNOWN_FIELDS))}
3. 时间格式 YYYY-MM；在职 end 为 null。
4. phone/email 等 PII 字段直接输出输入中的 PII:* token 原样，不得还原或改写。
5. 每个非 null 字段必须取自原文，并附 evidence 引用：
   {{"field_path": {{"block_id": 3, "start_offset": 5, "end_offset": 20, "quote": "IR 中逐字出现的引用串"}}}}
   quote 必须是输入 IR 对应 block 文本中逐字存在的子串（可为 PII token），不得编造引用。
输出 JSON 结构: {{"candidate": {{...}}, "evidence": {{field_path: {{block_id, start_offset, end_offset, quote}}}}}}"""

_BLOCK_MARKER_RE = re.compile(r"<!-- block_id: (\d+) kind: \w+ -->")


def parse_ir_blocks(ir: str) -> dict[int, str]:
    """解析 IR 的 block 标记，返回 block_id → block 文本（标记后到下一标记前）。"""
    blocks: dict[int, str] = {}
    matches = list(_BLOCK_MARKER_RE.finditer(ir))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(ir)
        blocks[int(m.group(1))] = ir[m.end():end].strip("\n")
    return blocks


def _verify_evidence(evidence: dict, masked_ir: str) -> dict:
    """A-13：quote 必须逐字出现在对应 block（脱敏后 IR）中，否则拒绝发布。

    offset 以 quote 实际出现位置为准（LLM offset 偏差时静默修正）；
    quote_hash 由系统计算（LLM 无法可靠计算 sha256）。
    """
    blocks = parse_ir_blocks(masked_ir)
    verified: dict = {}
    for field_path, ref in evidence.items():
        if not isinstance(ref, dict) or "block_id" not in ref or not ref.get("quote"):
            raise SchemaValidationError(f"evidence[{field_path}] 缺少 block_id 或 quote")
        block_text = blocks.get(int(ref["block_id"]))
        if block_text is None:
            raise SchemaValidationError(f"evidence[{field_path}] 引用了不存在的 block_id")
        quote = str(ref["quote"])
        pos = block_text.find(quote)
        if pos < 0:
            raise SchemaValidationError(f"evidence[{field_path}] 引用不存在于 IR（quote 未命中）")
        verified[field_path] = {
            "block_id": int(ref["block_id"]),
            "start_offset": pos,
            "end_offset": pos + len(quote),
            "quote_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest()[:16],
        }
    return verified


async def extract_candidate(llm, ir: str, source_channel: str) -> StructuredResult:
    """单次调用（A-1）：脱敏 → LLM → token 还原 → Schema 校验 → evidence 校验。

    evidence 只做「引用必须真实」的锚定校验（A-13），不做逐字段全覆盖——
    评测量化顺序：幻觉字段由评测 scorer（spec §4.3）阻断；全覆盖强制会因 LLM
    偶发漏引用把整份简历打成 not_retryable failed，压低 M3 成功率。
    """
    masked_ir, mapping = desensitize_text(ir)  # 出站前脱敏（双保险，fail-closed）
    raw = await llm.chat_json(EXTRACT_SYSTEM_PROMPT, f"<resume>\n{masked_ir}\n</resume>", {})
    candidate = raw.get("candidate")
    if not isinstance(candidate, dict):
        raise SchemaValidationError("LLM 输出缺少 candidate 对象")
    candidate = restore_pii_values(candidate, mapping)  # C-1：token → 明文后再校验/入库
    validate_candidate_json(candidate)
    evidence = _verify_evidence(raw.get("evidence") or {}, masked_ir)
    return StructuredResult(candidate=candidate, evidence=evidence, pii_mapping=mapping)