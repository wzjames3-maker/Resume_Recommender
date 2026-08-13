import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select

from app.models import ParseCheckpoint, ParseRun, ParseRunStatus
from app.services.audit import add_event
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.model_client import EmbeddingClient, LLMClient, ModelCallError
from app.services.resume.dedup import identity_hashes, normalize_skills
from app.services.resume.derive import derive_years_experience, detect_conflicts
from app.services.resume.extractor import LibreOfficeConverter, extract_resume
from app.services.resume.ingest import ingest, search_duplicates
from app.services.resume.ir import (
    IR_VALID_CHARS_THRESHOLD,
    build_import_ir,
    build_ir,
    count_valid_chars,
    validate_ir,
)
from app.services.resume.pii import PIIMappingEntry, PIIType, desensitize_text
from app.services.resume.profile import generate_profile
from app.services.resume.safety import (
    ParseSafetyError,
    check_file_signature,
    resource_limits,
    validate_docx_zip,
    validate_pdf,
)
from app.services.resume.schema import validate_candidate_json
from app.services.resume.segments import build_segments
from app.services.resume.structured import (
    RESUME_PROMPT_VERSION,
    StructuredResult,
    extract_candidate,
)


@dataclass
class PipelineOutcome:
    run_id: str
    status: ParseRunStatus
    candidate_id: int | None = None


def _sha256_json(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


async def _get_model_config(db, workspace_id: int, model_type: str):
    from app.models import ModelConfig
    row = await db.execute(select(ModelConfig).where(
        ModelConfig.workspace_id == workspace_id, ModelConfig.model_type == model_type))
    cfg = row.scalar_one_or_none()
    if cfg is None:
        raise ModelCallError(f"workspace 未配置 {model_type} 模型", retryable=False)
    return cfg


async def _get_llm(db, workspace_id: int) -> tuple[LLMClient, object]:
    from app.services.crypto import decrypt_secret

    cfg = await _get_model_config(db, workspace_id, "llm")
    return LLMClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name), cfg


async def _get_embedder(db, workspace_id: int) -> EmbeddingClient:
    from app.services.crypto import decrypt_secret

    cfg = await _get_model_config(db, workspace_id, "embedding")
    return EmbeddingClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


async def _embed_segments(db, workspace_id: int, candidate: dict) -> tuple[dict[str, str], dict[str, list[float]]]:
    """所有 embedding 前二次脱敏并去掉 identity PII（A-15）。"""
    raw_segments = build_segments(candidate)
    safe_segments = {name: desensitize_text(text)[0] for name, text in raw_segments.items() if text.strip()}
    nonempty = list(safe_segments.items())
    if not nonempty:
        return safe_segments, {}
    vectors = await (await _get_embedder(db, workspace_id)).embed([text for _, text in nonempty])
    if len(vectors) != len(nonempty):
        raise ModelCallError("embedding 返回数量与输入不一致", retryable=False)
    return safe_segments, dict(zip((name for name, _ in nonempty), vectors, strict=True))


def _stamp_evidence(evidence: dict, run_id: str) -> dict:
    return {path: {"ir_revision_id": run_id, **ref} for path, ref in evidence.items()}


def _content_type(fmt: str) -> str:
    return {
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "txt": "text/plain",
        "json": "application/json",
    }[fmt]


async def _save_checkpoint(db, run_id: str, structured: StructuredResult, profile: dict) -> None:
    """LLM 阶段检查点落库（PII 字段 AES-GCM 密文）。重试时复用，避免重复扣费。"""
    candidate_enc = encrypt_secret(json.dumps(structured.candidate, ensure_ascii=False, sort_keys=True))
    mapping_enc = encrypt_secret(json.dumps(
        [{"pii_type": e.pii_type.value, "value": e.value, "token": e.token} for e in structured.pii_mapping],
        ensure_ascii=False, sort_keys=True,
    ))
    db.add(ParseCheckpoint(run_id=run_id, llm_candidate_enc=candidate_enc,
                           llm_evidence=structured.evidence, llm_profile=profile,
                           pii_mapping_enc=mapping_enc))


async def _load_checkpoint(db, run_id: str) -> tuple[StructuredResult, dict] | None:
    """读取既有检查点；不存在返回 None。candidate/PII 密文解密后还原。"""
    cp = await db.get(ParseCheckpoint, run_id)
    if cp is None:
        return None
    candidate = json.loads(decrypt_secret(cp.llm_candidate_enc))
    mapping = [PIIMappingEntry(PIIType(m["pii_type"]), m["value"], m["token"])
               for m in json.loads(decrypt_secret(cp.pii_mapping_enc))]
    return StructuredResult(candidate=candidate, evidence=cp.llm_evidence, pii_mapping=mapping), cp.llm_profile


async def _run_import_pipeline(db, run: ParseRun, file_bytes: bytes) -> PipelineOutcome:
    """A-17：CSV/JSON 行级记录已结构化，跳过抽取阈值、LLM 与画像。"""
    try:
        payload = json.loads(file_bytes)
        record, meta = payload["record"], payload["meta"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ParseSafetyError(f"导入记录文件非法: {exc}") from exc
    validate_candidate_json({k: v for k, v in record.items() if k != "import_summary"})
    record["skills"] = normalize_skills(record.get("skills"))
    record["years_experience"] = derive_years_experience(record)
    conflicts = detect_conflicts(record)
    ir_text = build_import_ir(record, meta["source_channel"])
    _, pii_entries = desensitize_text(ir_text)  # 无 LLM 分支仍保存本地 PII 映射审计件
    run.ir_hash = hashlib.sha256(ir_text.encode("utf-8")).hexdigest()
    run.candidate_hash = _sha256_json(record)
    segments, vectors = await _embed_segments(db, run.workspace_id, record)
    phone_hash, email_hash = identity_hashes(record.get("phone"), record.get("email"))
    duplicates = await search_duplicates(db, run.workspace_id, record.get("name") or "", phone_hash, email_hash)
    cand = await ingest(
        db, workspace_id=run.workspace_id, run_id=run.run_id, revision_id=f"{run.run_id}:rev1",
        candidate=record, evidence={}, profile=None, ir_text=ir_text, ir_valid_chars=count_valid_chars(ir_text),
        file_hash=run.file_hash, storage_key=run.file_path, fmt="json", content_type=_content_type("json"),
        file_size=run.file_size, duplicates=duplicates, segments=segments, embeddings=vectors,
        pii_entries=pii_entries, conflicts=conflicts,
    )
    run.status = ParseRunStatus.succeeded
    await add_event(db, action="parse.run.succeeded", resource_type="parse_run",
                    resource_id=run.run_id, workspace_id=run.workspace_id, run_id=run.run_id,
                    revision_id=f"{run.run_id}:rev1", after_hash=run.candidate_hash,
                    payload={"candidate_id": cand.id})
    await db.commit()
    return PipelineOutcome(run_id=run.run_id, status=run.status, candidate_id=cand.id)


async def run_pipeline(db, run: ParseRun, file_bytes: bytes) -> PipelineOutcome:
    """完整流水线：safety → extract → IR → LLM → profile → dedup → embedding → ingest。
    返回状态；异常由调用方（Celery 任务）按失败分类处理。"""
    run.status = ParseRunStatus.processing
    run.error_message = None
    await db.commit()

    if run.format == "json":
        return await _run_import_pipeline(db, run, file_bytes)

    try:
        check_file_signature(file_bytes[:8], run.format)
    except ValueError as exc:
        raise ParseSafetyError(str(exc)) from exc

    # 1) 文件安全（fail-closed：加密/宏/压缩炸弹 → ParseSafetyError，不可重试）
    if run.format == "docx":
        try:
            validate_docx_zip(file_bytes)
        except ValueError as exc:
            raise ParseSafetyError(str(exc)) from exc
    elif run.format == "pdf":
        try:
            validate_pdf(run.file_path)
        except ValueError as exc:
            raise ParseSafetyError(str(exc)) from exc

    # 2) 抽取（docx 三通道 / pdf 文本层 / txt；.doc 经 LibreOffice 兜底）
    with resource_limits(cpu_seconds=60, mem_bytes=1024 * 1024 * 1024):
        blocks = extract_resume(run.file_path, run.format)

    # PRD F6 ②：docx 主力通道低于阈值时，也要走 LibreOffice 兜底后重抽。
    ir_text = build_ir(blocks, run.source_channel, run.parser_version, run.format)
    if run.format == "docx" and count_valid_chars(ir_text) < IR_VALID_CHARS_THRESHOLD:
        try:
            converted = LibreOfficeConverter().convert(run.file_path, "/tmp")
            try:
                blocks = extract_resume(converted, "docx")
                ir_text = build_ir(blocks, run.source_channel, "libreoffice/0.1", run.format)
            finally:
                import os
                os.remove(converted)
        except ValueError:
            # soffice 不可用或转换失败：保留主力通道结果，随后由阈值失败归类 not_retryable。
            pass
    run.ir_hash = hashlib.sha256(ir_text.encode("utf-8")).hexdigest()
    validate_ir(ir_text)

    # 3) LLM 结构化（PII 在 extract_candidate 内 fail-closed 脱敏）+ 画像
    #    检查点复用：重试/重启时不重复调用 LLM（PRD「重试不重复扣费」）。
    checkpoint = await _load_checkpoint(db, run.run_id)
    if checkpoint is not None:
        structured, profile = checkpoint
    else:
        llm, llm_cfg = await _get_llm(db, run.workspace_id)
        run.llm_provider = urlparse(llm_cfg.base_url).hostname or llm_cfg.base_url
        run.llm_model = llm_cfg.model_name
        run.prompt_version = RESUME_PROMPT_VERSION
        run.schema_version = "resume/v1"
        structured = await extract_candidate(llm, ir_text, run.source_channel)
        structured.candidate["years_experience"] = derive_years_experience(structured.candidate)
        profile_result = await generate_profile(llm, structured.candidate, structured.evidence)
        profile = {"values": profile_result.profile, "evidence": profile_result.evidence}
        await _save_checkpoint(db, run.run_id, structured, profile)
        await db.commit()
    structured.candidate["skills"] = normalize_skills(structured.candidate.get("skills"))
    conflicts = detect_conflicts(structured.candidate)
    run.candidate_hash = _sha256_json(structured.candidate)
    run.profile_hash = _sha256_json(profile)

    # 4) 查重（命中 → pending_review，不入 active）+ 五段真实 embedding
    phone_hash, email_hash = identity_hashes(
        structured.candidate.get("phone"), structured.candidate.get("email"))
    duplicates = await search_duplicates(db, run.workspace_id,
                                         structured.candidate.get("name") or "", phone_hash, email_hash)
    segments, vectors = await _embed_segments(db, run.workspace_id, structured.candidate)

    # 5) 入库（同 run 幂等，见 ingest）
    revision_id = f"{run.run_id}:rev1"
    cand = await ingest(db, workspace_id=run.workspace_id, run_id=run.run_id, revision_id=revision_id,
                         candidate=structured.candidate, evidence=_stamp_evidence(structured.evidence, run.run_id), profile=profile,
                         ir_text=ir_text, ir_valid_chars=count_valid_chars(ir_text),
                         file_hash=run.file_hash, storage_key=run.file_path, fmt=run.format,
                         content_type=_content_type(run.format), file_size=run.file_size, duplicates=duplicates,
                         segments=segments, embeddings=vectors, pii_entries=structured.pii_mapping,
                         conflicts=conflicts)

    run.status = ParseRunStatus.succeeded
    await add_event(db, action="parse.run.succeeded", resource_type="parse_run",
                    resource_id=run.run_id, workspace_id=run.workspace_id, run_id=run.run_id,
                    revision_id=f"{run.run_id}:rev1", after_hash=run.candidate_hash,
                    payload={"candidate_id": cand.id})
    await db.commit()
    return PipelineOutcome(run_id=run.run_id, status=ParseRunStatus.succeeded, candidate_id=cand.id)