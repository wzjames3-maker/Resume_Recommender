from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobRequirementOverride, JobRequirementRevision, JobStatus
from app.services.job_requirement import resolve_effective_ast
from app.services.search.cards import match_conditions


async def suitable_jobs_for_candidate(db: AsyncSession, workspace_id: int, fields: dict,
                                      profile: dict, limit: int = 5) -> list[dict]:
    """人→职位（J-8）：open 职位按命中条件数倒序取前 limit。"""
    jobs = (await db.execute(select(Job).where(
        Job.workspace_id == workspace_id, Job.status == JobStatus.open)
        .order_by(Job.updated_at.desc()))).scalars().all()
    scored = []
    for job in jobs:
        rev = await db.get(JobRequirementRevision, job.latest_revision_id)
        if rev is None:
            continue
        overrides = (await db.execute(select(JobRequirementOverride).where(
            JobRequirementOverride.revision_id == rev.id).order_by(JobRequirementOverride.id))).scalars().all()
        ast = resolve_effective_ast(rev, overrides)
        matched = match_conditions(fields, profile, ast)
        if matched:
            scored.append({
                "job_id": job.id, "name": job.name, "city": job.city,
                "headcount": job.headcount, "salary_range": job.salary_range,
                "matched_conditions": matched, "match_count": len(matched),
            })
    scored.sort(key=lambda x: x["match_count"], reverse=True)
    return scored[:limit]