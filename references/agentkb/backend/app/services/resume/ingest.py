from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Candidate,
    CandidateEmbedding,
    CandidateRevision,
    CandidateStatus,
    EmbeddingSegment,
    PIIMapping,
    PIIType,
    ResumeFile,
    ResumeIR,
)
from app.services.crypto import encrypt_secret
from app.services.resume.dedup import identity_hashes
from app.services.resume.ir_storage import encrypt_resume_ir
from app.services.resume.segments import build_search_text


async def search_duplicates(db: AsyncSession, workspace_id: int, name: str, phone_hash: str | None, email_hash: str | None) -> list[Candidate]:
    if not (phone_hash or email_hash):
        return []
    from sqlalchemy import or_
    stmt = select(Candidate).where(
        Candidate.workspace_id == workspace_id,
        Candidate.status.in_(["active", "deleted", "pending_review"]),
        Candidate.name == name,
        or_(Candidate.phone_hash == phone_hash, Candidate.email_hash == email_hash),
    )
    return list((await db.execute(stmt)).scalars().all())


async def ingest(db: AsyncSession, *, workspace_id: int, run_id: str, revision_id: str,
                  candidate: dict, evidence: dict, profile: dict | None,
                  ir_text: str, ir_valid_chars: int, file_hash: str, storage_key: str,
                  fmt: str, content_type: str, file_size: int, duplicates: list[Candidate],
                  segments: dict[str, str], embeddings: dict[str, list[float]],
                  pii_entries: list | None = None,
                  conflicts: list[dict] | None = None) -> Candidate:
    """入库核心：同一 run 幂等（重复 run 不再写）。返回候选人。"""
    existing_rev = await db.execute(select(CandidateRevision).where(CandidateRevision.run_id == run_id))
    if existing_rev.scalar_one_or_none() is not None:
        raise RuntimeError(f"run {run_id} 已入库，幂等跳过")

    phone_hash, email_hash = identity_hashes(candidate.get("phone"), candidate.get("email"))
    status = CandidateStatus.pending_review if duplicates else CandidateStatus.active
    # phone/email 只能进入 AES-GCM 列与 hash；CSV import_summary 不属于 candidate.json Schema，
    # 仅保留在 candidates.structured_data 并参与本地搜索/IR（schema spec §3.2/§4）。
    candidate_json = {k: v for k, v in candidate.items() if k not in {"phone", "email", "import_summary"}}
    stored_candidate = {**candidate_json}
    if candidate.get("import_summary"):
        stored_candidate["import_summary"] = candidate["import_summary"]
    cand = Candidate(
        workspace_id=workspace_id, status=status, name=candidate.get("name"),
        phone_enc=encrypt_secret(candidate["phone"]) if candidate.get("phone") else None,
        email_enc=encrypt_secret(candidate["email"]) if candidate.get("email") else None,
        phone_hash=phone_hash, email_hash=email_hash,
        structured_data=stored_candidate, search_text=build_search_text(stored_candidate),
    )
    db.add(cand)
    await db.flush()

    rev = CandidateRevision(candidate_id=cand.id, run_id=run_id, revision_id=revision_id,
                             candidate_json=candidate_json, profile_json=profile,
                             evidence=evidence, conflicts=conflicts or [])
    db.add(rev)
    await db.flush()
    cand.latest_revision_id = rev.id

    db.add(ResumeFile(run_id=run_id, candidate_id=cand.id, file_hash=file_hash,
                       storage_key=storage_key, format=fmt, file_size=file_size, content_type=content_type))
    db.add(ResumeIR(run_id=run_id, content=None, content_enc=encrypt_resume_ir(ir_text),
                    valid_chars=ir_valid_chars))

    # C-1：脱敏映射需持久化，token 明文不写库，原始值仅 AES-GCM 加密保存。
    for entry in pii_entries or []:
        db.add(PIIMapping(run_id=run_id, pii_type=PIIType(entry.pii_type.value),
                          content_hash=entry.content_hash, token_enc=encrypt_secret(entry.value),
                          ir_locator={"token": entry.token}))

    for seg, text in segments.items():
        if text.strip():
            vector = embeddings.get(seg)
            if vector is None:
                raise ValueError(f"缺少 {seg} 段 embedding")
            db.add(CandidateEmbedding(candidate_id=cand.id, revision_id=revision_id,
                                      segment=EmbeddingSegment(seg), text=text, embedding=vector))
    # 不在此 commit：run.status=succeeded、候选人、revision、向量必须由 pipeline 同一事务提交。
    # 否则 worker 重启可看见已入库但仍 processing 的半完成 run。
    await db.flush()
    return cand