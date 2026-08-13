from sqlalchemy import Integer, case, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Candidate,
    CandidateRevision,
    CandidateStatus,
    Assignment,
    InterviewResult,
    ParseRun,
    ResumeFile,
)
from app.services.search.schema import DEGREE_ORDINAL


async def list_candidates(db: AsyncSession, workspace_id: int, *, scopes: set[str],
                          skills: list[str] | None = None, city: str | None = None,
                          years_min: int | None = None, degree_at_least: str | None = None,
                          level: str | None = None, domain: str | None = None,
                           source_channel: str | None = None, referrer: str | None = None,
                           interview_result: str | None = None,
                           page: int = 1, page_size: int = 20) -> tuple[int, list[dict]]:
    statuses = [CandidateStatus(s) for s in scopes if s in {"active", "pending_review", "rejected", "hired", "deleted"}]
    if not statuses:
        return 0, []
    c = Candidate
    cr = CandidateRevision
    if interview_result is not None:
        try:
            result = InterviewResult(interview_result)
        except ValueError:
            raise ValueError("非法面试状态") from None
        base_result = select(Assignment.id).where(
            Assignment.workspace_id == workspace_id,
            Assignment.candidate_id == c.id,
            Assignment.interview_result == result,
        )
    else:
        base_result = None
    page, page_size = max(1, page), max(1, min(page_size, 100))
    base = (
        select(c.id, c.name, c.status, c.created_at)
        .join(cr, cr.id == c.latest_revision_id)
        .where(c.workspace_id == workspace_id, c.status.in_(statuses))
    )
    if base_result is not None:
        base = base.where(exists(base_result))
    if skills:
        for s in skills:
            base = base.where(c.search_tsv.op("@@")(func.plainto_tsquery("simple", s)))
    if city:
        base = base.where((c.structured_data.op("->>")("city") == city)
                          | (c.structured_data.op("->>")("expected_city") == city))
    if years_min is not None:
        base = base.where(func.coalesce(cast(c.structured_data.op("->>")("years_experience"), Integer), -1) >= years_min)
    if degree_at_least:
        low = DEGREE_ORDINAL.get(degree_at_least)
        if low is not None:
            ordinal_case = case(
                *[(c.structured_data.op("->>")("highest_degree") == d, o) for d, o in DEGREE_ORDINAL.items()],
                else_=0)
            base = base.where(ordinal_case >= low)
    if level:
        base = base.where(cr.profile_json["values"]["level"].astext == level)
    if domain:
        base = base.where(cr.profile_json["values"]["domain"].astext == domain)
    if source_channel:
        # EXISTS 避免多份简历 JOIN 产生重复行
        sub = select(ResumeFile.id).join(ParseRun, ParseRun.run_id == ResumeFile.run_id) \
            .where(ResumeFile.candidate_id == c.id, ParseRun.source_channel == source_channel)
        base = base.where(exists(sub))
    if referrer:
        sub = select(ResumeFile.id).join(ParseRun, ParseRun.run_id == ResumeFile.run_id) \
            .where(ResumeFile.candidate_id == c.id, ParseRun.referrer == referrer)
        base = base.where(exists(sub))

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = await db.execute(base.order_by(c.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return (total, [{"candidate_id": cid, "name": name, "status": status.value,
                     "created_at": created.isoformat() if created else None}
                    for cid, name, status, created in rows])
