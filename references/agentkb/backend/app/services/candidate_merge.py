from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Candidate,
    CandidateEmbedding,
    CandidateEvent,
    CandidateEventType,
    CandidateOverride,
    CandidateRevision,
    CandidateStatus,
    ResumeFile,
)
from app.services.resume.segments import build_search_text


class MergeError(Exception):
    pass


class MergeConflictError(Exception):
    pass


_HISTORY_MODELS = (CandidateRevision, CandidateEmbedding, ResumeFile, CandidateEvent, CandidateOverride)


async def merge_candidates(db: AsyncSession, *, primary: Candidate, absorbed: Candidate,
                           base_revision_id: int, actor_id: int) -> Candidate:
    """合并重复候选人（N-1/N-2）：被并入者的历史重挂到主体，主体以最新 revision 为 base。"""
    if primary.id == absorbed.id:
        raise MergeError("不能与自身合并")
    # 行锁：串行化同一对候选人的并发合并（A併B 与 B併A 同时提交的竞态）
    await db.execute(select(Candidate.id).where(
        Candidate.id.in_([primary.id, absorbed.id])).with_for_update())
    if base_revision_id != primary.latest_revision_id:
        raise MergeConflictError("候选人已被修改，请刷新后重试")
    if CandidateStatus.hired in (primary.status, absorbed.status):
        raise MergeError("入职员工不可合并")
    if CandidateStatus.deleted in (primary.status, absorbed.status):
        raise MergeError("已删除候选人不可合并")

    # 1) 历史重挂（revision/嵌入/文件/事件/override 全部并入主体，保留全部简历与历史）
    for model in _HISTORY_MODELS:
        await db.execute(update(model).where(model.candidate_id == absorbed.id).values(candidate_id=primary.id))

    # 2) 最新 revision = 两人全 revision 中 created_at 最晚一条 → 合并 base
    newest = (await db.execute(select(CandidateRevision).where(
        CandidateRevision.candidate_id == primary.id)
        .order_by(CandidateRevision.created_at.desc(), CandidateRevision.id.desc()))).scalars().first()
    if newest is None:
        raise MergeError("无可合并的解析记录")
    primary.latest_revision_id = newest.id
    base = dict(newest.candidate_json)
    primary.structured_data = base
    primary.search_text = build_search_text(base)  # 触发 search_tsv 同步（N-6）
    primary.name = base.get("name") or primary.name

    # 3) PII 补缺：主体无 phone/email 时用被并入者的（人工已确认合并主体）
    if not primary.phone_hash and absorbed.phone_hash:
        primary.phone_enc, primary.phone_hash = absorbed.phone_enc, absorbed.phone_hash
    if not primary.email_hash and absorbed.email_hash:
        primary.email_enc, primary.email_hash = absorbed.email_enc, absorbed.email_hash

    # 4) 被并入者 → deleted（30 天可恢复；其数据已并入主体副本）
    absorbed.status = CandidateStatus.deleted
    absorbed.deleted_until = datetime.now(UTC) + timedelta(days=30)

    # 5) 主体追加 merged 事件（N-4）
    db.add(CandidateEvent(candidate_id=primary.id, event_type=CandidateEventType.merged,
                          title=f"合并候选人 {absorbed.id}",
                          detail={"absorbed_id": absorbed.id, "absorbed_name": absorbed.name},
                          actor_id=actor_id))
    return primary