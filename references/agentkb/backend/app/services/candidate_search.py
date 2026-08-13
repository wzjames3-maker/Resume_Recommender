from dataclasses import dataclass

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, and_, bindparam, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EMBEDDING_DIM,
    Assignment,
    AssignmentStatus,
    Candidate,
    CandidateEmbedding,
    CandidateRevision,
    CandidateStatus,
)
from app.rag.retriever import rrf_merge, rrf_scores
from app.services.search.schema import (
    build_condition_filter,
    requires_profile_join,
    validate_conditions,
)

ALLOWED_SCOPES_BY_ROLE = {
    "member": {"active", "rejected"},
    "admin": {"active", "rejected", "hired"},
    "owner": {"active", "rejected", "hired"},
}
_SEARCHABLE_STATUS = {CandidateStatus.active, CandidateStatus.rejected, CandidateStatus.hired}


@dataclass
class CandidateHit:
    candidate_id: int
    score: float


async def search_candidates(db: AsyncSession, workspace_id: int, query_embedding: list[float],
                             query_text: str, conditions: list, scopes: set[str],
                             top_k: int = 20, assignment_history: list[dict] | None = None) -> list[CandidateHit]:
    """候选人混合检索（S-2）：结构化过滤 ∩ 五段向量 RRF ∩ search_tsv 全文，含池过滤。

    命中条件标注在 cards 层统一计算（需 profile_json），此处只返回 candidate_id + score。
    """
    validate_conditions(conditions)
    statuses = [CandidateStatus(s) for s in scopes if s in _SEARCHABLE_STATUS]
    if not statuses:
        return []
    cond_expr = build_condition_filter(conditions)
    need_profile = requires_profile_join(conditions)

    base = select(Candidate.id).where(Candidate.workspace_id == workspace_id, Candidate.status.in_(statuses))
    if not any(cond.get("field") in {"interview_result", "assignment_status"}
               for cond in conditions):
        base = base.where(~exists(select(Assignment.id).where(
            Assignment.workspace_id == workspace_id,
            Assignment.candidate_id == Candidate.id,
            Assignment.status.in_({AssignmentStatus.closed_after_hire, AssignmentStatus.closed_by_job}),
        )))
    if need_profile:
        base = base.join(CandidateRevision, CandidateRevision.id == Candidate.latest_revision_id)
    if cond_expr is not None:
        base = base.where(cond_expr)
    if assignment_history:
        base = base.where(exists(select(Assignment.id).where(
            Assignment.workspace_id == workspace_id,
            Assignment.candidate_id == Candidate.id,
            Assignment.status == AssignmentStatus.offer_rejected,
        )))
    filtered = base.cte("filtered")

    # 1) 向量召回：五段嵌入取每候选最小余弦距离，仅限过滤集内候选
    ce = CandidateEmbedding.__table__
    c = Candidate.__table__
    cr = CandidateRevision.__table__
    distance = func.min(ce.c.embedding.op("<=>")(bindparam("q", type_=Vector(EMBEDDING_DIM)))).cast(Float)
    vec_query = (
        select(ce.c.candidate_id, distance.label("dist"))
        .select_from(
            ce.join(c, c.c.id == ce.c.candidate_id)
            .join(cr, and_(cr.c.id == c.c.latest_revision_id, cr.c.revision_id == ce.c.revision_id))
            .join(filtered, filtered.c.id == c.c.id)
        )
        .group_by(ce.c.candidate_id)
        .order_by(distance)
        .limit(top_k * 2)
    )
    vec_rows = await db.execute(vec_query, {"q": query_embedding})
    vec_ids = [r[0] for r in vec_rows.all()]

    # 2) 全文召回（search_tsv，simple 配置）
    full_stmt = select(Candidate.id).where(
        Candidate.workspace_id == workspace_id,
        Candidate.status.in_(statuses),
        Candidate.search_tsv.op("@@")(func.plainto_tsquery("simple", query_text)),
    )
    if not any(cond.get("field") in {"interview_result", "assignment_status"}
               for cond in conditions):
        full_stmt = full_stmt.where(~exists(select(Assignment.id).where(
            Assignment.workspace_id == workspace_id,
            Assignment.candidate_id == Candidate.id,
            Assignment.status.in_({AssignmentStatus.closed_after_hire, AssignmentStatus.closed_by_job}),
        )))
    if need_profile:
        full_stmt = full_stmt.join(CandidateRevision, CandidateRevision.id == Candidate.latest_revision_id)
    if cond_expr is not None:
        full_stmt = full_stmt.where(cond_expr)
    if assignment_history:
        full_stmt = full_stmt.where(exists(select(Assignment.id).where(
            Assignment.workspace_id == workspace_id,
            Assignment.candidate_id == Candidate.id,
            Assignment.status == AssignmentStatus.offer_rejected,
        )))
    full_rows = await db.execute(full_stmt.limit(top_k * 2))
    full_ids = [r[0] for r in full_rows.all()]

    rankings = [vec_ids, full_ids]
    scores = rrf_scores(rankings)
    merged = rrf_merge(rankings)[:top_k]
    if not merged:
        return []
    max_score = max((scores[i] for i in merged), default=0.0)
    return [
        CandidateHit(candidate_id=cid, score=round((scores[cid] / max_score), 4) if max_score > 0 else 0.0)
        for cid in merged
    ]
