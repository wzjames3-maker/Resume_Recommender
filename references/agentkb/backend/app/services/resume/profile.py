import json
from dataclasses import dataclass

from app.services.resume.pii import desensitize_text

PROFILE_SCHEMA_VERSION = "profile/v1"

LEVELS = {"Junior", "Mid", "Senior", "Staff", "Principal"}
DEPTHS = {"Low", "Medium", "High", "Expert"}
DOMAINS = {"金融科技", "电商", "AI", "医疗", "供应链"}
INFLUENCE = {"个人贡献者", "小组", "团队负责", "跨团队", "组织级"}
MANAGEMENT = {"无", "导师", "技术负责", "团队管理", "总监级"}
STABILITY = {"稳定", "正常", "频繁变动", "风险"}
GROWTH = {"上升", "平稳", "平台期", "下滑"}
COMMUNICATION = {"低", "中", "高"}

ENUM_FIELDS = {
    "level": LEVELS, "professional_depth": DEPTHS,
    "influence_scope": INFLUENCE, "management": MANAGEMENT,
    "stability": STABILITY, "growth_trend": GROWTH, "communication": COMMUNICATION,
}


class ProfileValidationError(Exception):
    pass


@dataclass
class ProfileResult:
    profile: dict
    evidence: dict


def validate_profile_json(profile: dict) -> None:
    if not isinstance(profile, dict):
        raise ProfileValidationError("profile 必须为对象")
    known = set(ENUM_FIELDS) | {"domain", "strengths", "risks", "career_pattern"}
    unknown = set(profile) - known
    if unknown:
        raise ProfileValidationError(f"profile 未知字段: {sorted(unknown)}")
    for field, allowed in ENUM_FIELDS.items():
        v = profile.get(field)
        if v is not None and v not in allowed:
            raise ProfileValidationError(f"profile.{field}={v!r} 非法枚举")
    # Schema spec §1.5：domain 为开放枚举，允许非空字符串（评测标签集另行冻结）。
    if profile.get("domain") is not None and (not isinstance(profile["domain"], str) or len(profile["domain"]) > 2000):
        raise ProfileValidationError("profile.domain 必须为字符串或 null")
    for k in ("strengths", "risks", "career_pattern"):
        v = profile.get(k)
        if v is not None and (not isinstance(v, str) or len(v) > 2000):
            raise ProfileValidationError(f"profile.{k} 必须为字符串且 ≤2000")


PROFILE_SYSTEM_PROMPT = f"""你是人才画像分析师。基于候选人结构化信息输出八维固定画像 + 开放洞察。

八维枚举（必须严格使用，无法确定标 null，禁止编造）:
- level: {sorted(LEVELS)}
- professional_depth: {sorted(DEPTHS)}
- domain: {sorted(DOMAINS)}（开放枚举，可合理追加）
- influence_scope: {sorted(INFLUENCE)}
- management: {sorted(MANAGEMENT)}
- stability: {sorted(STABILITY)}
- growth_trend: {sorted(GROWTH)}
- communication: {sorted(COMMUNICATION)}
开放洞察: strengths / risks / career_pattern（自由文本，仅供 HR 阅读）

每个非 null 结论必须通过 evidence 引用至少一个候选人既有 evidence 字段路径；无依据返回 null。
输出 JSON: {{"profile": {{...}}, "evidence": {{"level": ["work[0].content"]}}}}"""


_PII_OUTBOUND_FIELDS = ("phone", "email", "name")  # A-15：身份/联系字段不出站


def _mask_pii_values(value):
    """递归脱敏候选自由文本字段（保留真实换行，使地址等行锚定正则可命中）。

    json.dumps 会把字符串内换行转义为 \\n，行锚定的地址正则无法识别；
    故先对 dict 逐字段脱敏、再序列化，避免自由文本中的地址/电话出站泄漏。
    """
    if isinstance(value, dict):
        return {k: _mask_pii_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_pii_values(v) for v in value]
    if isinstance(value, str):
        return desensitize_text(value)[0]
    return value


async def generate_profile(llm, candidate: dict, evidence: dict) -> ProfileResult:
    safe = {k: v for k, v in candidate.items() if k not in _PII_OUTBOUND_FIELDS}
    prompt = json.dumps({"candidate": _mask_pii_values(safe)}, ensure_ascii=False)
    raw = await llm.chat_json(PROFILE_SYSTEM_PROMPT, prompt, {})
    profile = raw.get("profile")
    if not isinstance(profile, dict):
        raise ProfileValidationError("LLM 输出缺少 profile 对象")
    validate_profile_json(profile)
    profile_evidence = raw.get("evidence") or {}
    non_null = {key for key, value in profile.items() if value is not None}
    if set(profile_evidence) != non_null:
        raise ProfileValidationError("画像非空字段必须逐项提供 evidence")
    for field, refs in profile_evidence.items():
        if not isinstance(refs, list) or not refs or any(ref not in evidence for ref in refs):
            raise ProfileValidationError(f"profile.{field} evidence 未引用候选人已有证据")
    return ProfileResult(profile=profile, evidence=profile_evidence)