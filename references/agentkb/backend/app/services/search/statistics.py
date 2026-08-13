from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    Candidate,
    CandidateRevision,
    CandidateStatus,
)
from app.services.search.extractor import STAT_GROUP_BY
from app.services.search.schema import (
    build_condition_filter,
    requires_profile_join,
    validate_conditions,
)

_PROFILE_DIMS = {"level", "domain", "management"}
_SEARCHABLE_STATUS = {"active", "rejected", "hired"}


def _dimension_expr(dim):
    if dim in _PROFILE_DIMS:
        return func.coalesce(CandidateRevision.profile_json["values"][dim].astext, "未知").label("dim_key")
    return func.coalesce(Candidate.structured_data.op("->>")(dim), "未知").label("dim_key")


async def compute_statistics(db: AsyncSession, *, workspace_id: int, conditions: list,
                             scopes: set[str], group_by: str | None,
                             assignment_history: list[dict] | None = None) -> dict:
    """统计查询（T-1/T-2/T-3）：计数 + 分布。条件/画像复用搜人编译规则，池过滤与 ACL 由调用方保证。"""
    validate_conditions(conditions)
    if group_by is not None and group_by not in STAT_GROUP_BY:
        raise ValueError(f"非法统计维度: {group_by}")
    statuses = [CandidateStatus(s) for s in scopes if s in _SEARCHABLE_STATUS]
    if not statuses:
        return {"count": 0, "dimension": group_by, "distribution": []}
    need_profile = requires_profile_join(conditions) or (group_by in _PROFILE_DIMS)
    cols = [Candidate.id]
    if group_by:
        cols.append(_dimension_expr(group_by))
    base = select(*cols).where(
        Candidate.workspace_id == workspace_id, Candidate.status.in_(statuses))
    if need_profile:
        base = base.join(CandidateRevision, CandidateRevision.id == Candidate.latest_revision_id)
    cond_expr = build_condition_filter(conditions)
    if cond_expr is not None:
        base = base.where(cond_expr)
    if assignment_history:
        base = base.where(exists(select(Assignment.id).where(
            Assignment.workspace_id == workspace_id,
            Assignment.candidate_id == Candidate.id,
            Assignment.status == AssignmentStatus.offer_rejected,
        )))

    sub = base.subquery()
    count = (await db.execute(select(func.count()).select_from(sub))).scalar_one()
    distribution = []
    if group_by:
        rows = await db.execute(
            select(sub.c.dim_key, func.count().label("cnt"))
            .select_from(sub).group_by(sub.c.dim_key)
            .order_by(func.count().desc()))
        distribution = [{"key": k, "count": c} for k, c in rows.all()]
    return {"count": count, "dimension": group_by, "distribution": distribution}
