from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Candidate,
    CandidateRevision,
    CandidateStatus,
    Job,
    JobRequirementRevision,
    JobStatus,
)
from app.services.job_requirement import (
    JOB_REQUIREMENT_PROMPT_VERSION,
    parse_job_requirement,
)
from app.services.search.schema import (
    SEARCH_SCHEMA_VERSION,
    build_condition_filter,
    requires_profile_join,
)


class JobConflictError(Exception):
    pass


async def create_job(db: AsyncSession, *, workspace_id: int, name: str, description: str,
                     headcount: int, city: str | None, salary_range: str | None,
                     actor_id: int, llm) -> tuple[Job, list]:
    """创建职位 + 解析岗位要求 + 建首个 revision（J-2/J-5）。"""
    parsed = await parse_job_requirement(llm, description)
    job = Job(workspace_id=workspace_id, name=name, description=description,
              headcount=headcount, city=city, salary_range=salary_range,
              status=JobStatus.open, created_by=actor_id)
    db.add(job)
    await db.flush()
    rev = JobRequirementRevision(job_id=job.id, revision=1, description=description,
                                 parsed_ast=parsed["conditions"],
                                 schema_version=SEARCH_SCHEMA_VERSION,
                                 prompt_version=JOB_REQUIREMENT_PROMPT_VERSION,
                                 evidence=parsed["evidence"], created_by=actor_id)
    db.add(rev)
    await db.flush()
    job.latest_revision_id = rev.id
    return job, parsed["conditions"]


async def update_job(db: AsyncSession, *, job: Job, base_revision_id: int,
                     name: str | None, description: str | None, headcount: int | None,
                     city: str | None, salary_range: str | None, status: str | None,
                     actor_id: int, llm) -> tuple[Job, bool]:
    """编辑职位。description 变更 → 新 revision + 重新解析；乐观锁 base_revision_id（J-5）。

    行锁（SELECT ... FOR UPDATE）串行化同一职位的并发 PATCH，避免 TOCTOU 竞态（I-2）。
    """
    await db.execute(select(Job.id).where(Job.id == job.id).with_for_update())
    if base_revision_id != job.latest_revision_id:
        raise JobConflictError("职位要求已被修改，请刷新后重试")
    if name is not None:
        job.name = name
    if headcount is not None:
        job.headcount = headcount
    if city is not None:
        job.city = city
    if salary_range is not None:
        job.salary_range = salary_range
    if status is not None:
        if job.status is JobStatus.closed and status == JobStatus.open.value:
            raise JobConflictError("已关闭职位不可重新开放，请新建职位")
        job.status = JobStatus(status)
    if description is not None and description != job.description:
        job.description = description
        parsed = await parse_job_requirement(llm, description)
        latest = (await db.execute(select(func.max(JobRequirementRevision.revision))
                                   .where(JobRequirementRevision.job_id == job.id))).scalar_one() or 0
        rev = JobRequirementRevision(job_id=job.id, revision=latest + 1, description=description,
                                     parsed_ast=parsed["conditions"],
                                     schema_version=SEARCH_SCHEMA_VERSION,
                                     prompt_version=JOB_REQUIREMENT_PROMPT_VERSION,
                                     evidence=parsed["evidence"], created_by=actor_id)
        db.add(rev)
        await db.flush()
        job.latest_revision_id = rev.id
        return job, True
    return job, False


async def list_jobs(db: AsyncSession, workspace_id: int, *, status: str | None = None,
                    page: int = 1, page_size: int = 50) -> tuple[int, list[dict]]:
    page, page_size = max(1, page), max(1, min(page_size, 100))
    stmt = select(Job).where(Job.workspace_id == workspace_id)
    if status == "open":
        stmt = stmt.where(Job.status == JobStatus.open)
    elif status == "closed":
        stmt = stmt.where(Job.status == JobStatus.closed)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Job.created_at.desc())
                             .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return total, [{
        "job_id": j.id, "name": j.name, "status": j.status.value, "city": j.city,
        "headcount": j.headcount, "salary_range": j.salary_range,
        "description": j.description, "latest_revision_id": j.latest_revision_id,
        "created_at": j.created_at.isoformat() if j.created_at else None,
    } for j in rows]


async def resolve_job(db: AsyncSession, workspace_id: int, *, job_id: int | None,
                      job_title: str | None) -> tuple[Job | None, list[dict], bool]:
    """职位定位（J-3）：job_id 直接命中；名称唯一直接命中；同名多选返回候选；找不到返回 None。"""
    if job_id is not None:
        job = await db.get(Job, job_id)
        if job is not None and job.workspace_id == workspace_id:
            return job, [], False
        return None, [], False
    if job_title:
        rows = (await db.execute(select(Job).where(
            Job.workspace_id == workspace_id,
            Job.name.ilike(f"%{job_title}%")))).scalars().all()
        open_rows = [j for j in rows if j.status is JobStatus.open]
        if len(open_rows) == 1:
            return open_rows[0], [], False
        if len(open_rows) > 1:
            candidates = [{
                "job_id": j.id, "name": j.name, "city": j.city,
                "headcount": j.headcount, "salary_range": j.salary_range,
            } for j in open_rows]
            return None, candidates, True
        if rows:  # 仅命中已关闭职位：返回给 flow 报告「已关闭」
            return rows[0], [], False
    return None, [], False


async def count_matching_candidates(db: AsyncSession, workspace_id: int, conditions: list,
                                    scopes: set[str]) -> int:
    """职位→人匹配计数（J-7）：与 search_candidates 同口径（active/rejected/hired ∩ scopes）。"""
    from app.services.candidate_search import _SEARCHABLE_STATUS

    statuses = [CandidateStatus(s) for s in scopes if s in _SEARCHABLE_STATUS]
    if not statuses or not conditions:
        return 0
    expr = build_condition_filter(conditions)
    stmt = select(func.count(Candidate.id)).where(
        Candidate.workspace_id == workspace_id, Candidate.status.in_(statuses))
    if requires_profile_join(conditions):
        stmt = stmt.join(CandidateRevision, CandidateRevision.id == Candidate.latest_revision_id)
    if expr is not None:
        stmt = stmt.where(expr)
    return (await db.execute(stmt)).scalar_one()
