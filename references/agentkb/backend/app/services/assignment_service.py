from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    Candidate,
    CandidateEventType,
    CandidateStatus,
    Job,
    JobStatus,
)
from app.services.candidate_lifecycle import append_event

TERMINAL = {AssignmentStatus.hired, AssignmentStatus.offer_rejected, AssignmentStatus.rejected,
            AssignmentStatus.closed_after_hire, AssignmentStatus.closed_by_job}
IN_PROGRESS = {AssignmentStatus.pending_screen, AssignmentStatus.screen_passed,
               AssignmentStatus.interviewing, AssignmentStatus.offer}

_TRANSITIONS = {
    AssignmentStatus.pending_screen: {AssignmentStatus.screen_passed, AssignmentStatus.rejected, AssignmentStatus.closed_by_job},
    AssignmentStatus.screen_passed: {AssignmentStatus.interviewing, AssignmentStatus.rejected, AssignmentStatus.closed_by_job},
    AssignmentStatus.interviewing: {AssignmentStatus.offer, AssignmentStatus.rejected, AssignmentStatus.closed_by_job},
    AssignmentStatus.offer: {AssignmentStatus.offer_rejected, AssignmentStatus.rejected, AssignmentStatus.closed_by_job},
    # hired 仅由 hire() 入职聚合产生（C-2：禁止 transition 直达绕过聚合）
}


class AssignmentError(Exception):
    pass


async def _lock_candidate(db: AsyncSession, candidate_id: int) -> None:
    """候选级行锁（I-2）：串行化同一候选人的并发流转/入职/重算，覆盖 PRD 乐观锁意图。"""
    await db.execute(select(Candidate.id).where(Candidate.id == candidate_id).with_for_update())


async def _reload_job(db: AsyncSession, job_id: int) -> Job:
    row = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    return row.scalar_one()


async def recompute_candidate_pool(db: AsyncSession, candidate_id: int) -> None:
    """F15 三池规则（P-5）：任一 hired→hired；有进行中→active；否则最近终态 rejected/offer_rejected→rejected，closed_* 保持。"""
    cand = await db.get(Candidate, candidate_id)
    rows = (await db.execute(select(Assignment).where(
        Assignment.candidate_id == candidate_id))).scalars().all()
    if any(a.status is AssignmentStatus.hired for a in rows):
        cand.status = CandidateStatus.hired
    elif any(a.status in IN_PROGRESS for a in rows):
        cand.status = CandidateStatus.active
    else:
        latest = None
        for a in rows:
            if a.status in TERMINAL and (latest is None or a.updated_at > latest.updated_at):
                latest = a
        if latest is not None and latest.status in (AssignmentStatus.rejected, AssignmentStatus.offer_rejected):
            cand.status = CandidateStatus.rejected
        else:
            cand.status = CandidateStatus.active  # closed_* 保持前池（默认 active）


async def create_assignment(db: AsyncSession, *, workspace_id: int, candidate_id: int, job_id: int,
                            idempotency_key: str | None, actor_id: int) -> Assignment:
    """加入待面试（P-1/P-4/P-7）：职位在招、HC 未满、幂等去重、rejected 回 active。"""
    if idempotency_key:
        existing = (await db.execute(select(Assignment).where(
            Assignment.workspace_id == workspace_id, Assignment.idempotency_key == idempotency_key))).scalar_one_or_none()
        if existing is not None:
            return existing
    job = await _reload_job(db, job_id)
    if job.status is not JobStatus.open:
        raise AssignmentError("职位已关闭，不可新增指派")
    if job.hc_filled >= job.headcount:
        raise AssignmentError("HC 已满，无法加入待面试")
    cand = await db.get(Candidate, candidate_id)
    if cand is None or cand.workspace_id != workspace_id:
        raise AssignmentError("候选人不存在")
    if cand.status is CandidateStatus.hired:
        raise AssignmentError("入职员工禁止重新指派")
    dup = (await db.execute(select(Assignment).where(
        Assignment.candidate_id == candidate_id, Assignment.job_id == job_id))).scalar_one_or_none()
    if dup is not None:
        raise AssignmentError("该候选人已在本职位流程中")
    a = Assignment(workspace_id=workspace_id, candidate_id=candidate_id, job_id=job_id,
                   status=AssignmentStatus.pending_screen, idempotency_key=idempotency_key,
                   created_by=actor_id)
    db.add(a)
    await db.flush()
    await _lock_candidate(db, candidate_id)
    await recompute_candidate_pool(db, candidate_id)  # rejected 候选人重新指派 → active
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.status_changed,
                       title="加入待面试", detail={"job_id": job_id, "to": "pending_screen"},
                       actor_id=actor_id)
    return a


async def _adjust_hc(job: Job, prev: AssignmentStatus, next_: AssignmentStatus) -> None:
    """HC 算术（P-4）：offer 占 reservation，hired 转 filled，终态释放。"""
    if prev is AssignmentStatus.offer and next_ is not AssignmentStatus.offer:
        job.hc_reserved = max(0, job.hc_reserved - 1)  # 离开 offer：释放 reservation
    if next_ is AssignmentStatus.offer:
        job.hc_reserved += 1  # 进入 offer：占 reservation
    if next_ is AssignmentStatus.hired:
        job.hc_filled += 1  # offer→hired 已释放 reservation，这里只转 filled


async def transition(db: AsyncSession, *, assignment: Assignment, to_state: str,
                     reject_reason: str | None = None, close_reason: str | None = None,
                     actor_id: int) -> Assignment:
    """状态流转（P-2/P-3/P-6）：终态不可流转；淘汰必填原因；closed_by_job 仅 admin（API 层校验）。"""
    try:
        target = AssignmentStatus(to_state)
    except ValueError:
        raise AssignmentError(f"非法目标状态: {to_state}") from None
    if assignment.status in TERMINAL:
        raise AssignmentError("终态指派不可再流转")
    if target not in _TRANSITIONS[assignment.status]:
        raise AssignmentError(f"不允许从 {assignment.status.value} 流转到 {target.value}")
    if target is AssignmentStatus.rejected and not reject_reason:
        raise AssignmentError("淘汰原因必填")
    job = await _reload_job(db, assignment.job_id)
    await _lock_candidate(db, assignment.candidate_id)
    assignment = (await db.execute(select(Assignment).where(
        Assignment.id == assignment.id).with_for_update())).scalar_one()
    if assignment.status in TERMINAL:
        raise AssignmentError("终态指派不可再流转")
    if target not in _TRANSITIONS[assignment.status]:
        raise AssignmentError(f"不允许从 {assignment.status.value} 流转到 {target.value}")
    prev = assignment.status
    if target is AssignmentStatus.offer:
        if job.hc_filled + job.hc_reserved >= job.headcount:
            raise AssignmentError("HC 已满，无法发 offer")
        if job.status is not JobStatus.open:
            raise AssignmentError("职位已关闭，不可进入 offer")
        # F14 闸门：当前轮反馈须 recommend 且完整（P8 I-2）
        from app.models import FeedbackConclusion, InterviewRound
        latest = (await db.execute(select(InterviewRound).where(
            InterviewRound.assignment_id == assignment.id)
            .order_by(InterviewRound.round_no.desc()).limit(1))).scalars().first()
        if latest is None or latest.conclusion is not FeedbackConclusion.recommend \
                or latest.score is None or not latest.comment:
            raise AssignmentError("当前面试轮反馈须为 recommend 且评分/评语完整才可发 offer")
    if target is AssignmentStatus.interviewing:
        # F14 闸门：须先安排面试（P8 I-2）
        from app.models import InterviewRound
        has_round = (await db.execute(select(InterviewRound.id).where(
            InterviewRound.assignment_id == assignment.id).limit(1))).scalar_one_or_none()
        if has_round is None:
            raise AssignmentError("需先安排面试才能进入面试中")
    if target is AssignmentStatus.screen_passed and job.status is not JobStatus.open:
        raise AssignmentError("职位已关闭，不可进入初筛")
    assignment.status = target
    if target is AssignmentStatus.rejected:
        assignment.reject_reason = reject_reason
    if target is AssignmentStatus.closed_by_job:
        if not close_reason:
            raise AssignmentError("关闭原因必填")
        if job.status is not JobStatus.closed:
            raise AssignmentError("仅职位关闭后可关闭余下指派")
        assignment.close_reason = close_reason
    await _adjust_hc(job, prev, target)
    await recompute_candidate_pool(db, assignment.candidate_id)
    await append_event(db, candidate_id=assignment.candidate_id, event_type=CandidateEventType.status_changed,
                       title=f"指派流转 {prev.value}→{target.value}",
                       detail={"assignment_id": assignment.id, "job_id": assignment.job_id,
                               "from": prev.value, "to": target.value,
                               "reason": reject_reason or close_reason},
                       actor_id=actor_id)
    return assignment


async def hire(db: AsyncSession, *, assignment: Assignment, actor_id: int) -> Assignment:
    """入职聚合（P-5）：offer→hired，原子关闭该候选人其余进行中指派 → closed_after_hire，池 → hired。"""
    if assignment.status is not AssignmentStatus.offer:
        raise AssignmentError("仅 offer 状态可入职")
    job = await _reload_job(db, assignment.job_id)
    await _lock_candidate(db, assignment.candidate_id)
    assignment = (await db.execute(select(Assignment).where(
        Assignment.id == assignment.id).with_for_update())).scalar_one()
    if assignment.status is not AssignmentStatus.offer:
        raise AssignmentError("仅 offer 状态可入职")
    assignment.status = AssignmentStatus.hired
    await _adjust_hc(job, AssignmentStatus.offer, AssignmentStatus.hired)
    # 关闭其余进行中指派
    others = (await db.execute(select(Assignment).where(
        Assignment.candidate_id == assignment.candidate_id,
        Assignment.id != assignment.id,
        Assignment.status.in_(IN_PROGRESS)))).scalars().all()
    for other in others:
        prev_status = other.status
        other.status = AssignmentStatus.closed_after_hire
        other.close_reason = f"候选人入职职位 {job.name}"
        ojob = await _reload_job(db, other.job_id)
        await _adjust_hc(ojob, prev_status, AssignmentStatus.closed_after_hire)
    await recompute_candidate_pool(db, assignment.candidate_id)
    await append_event(db, candidate_id=assignment.candidate_id, event_type=CandidateEventType.status_changed,
                       title="入职", detail={"assignment_id": assignment.id, "job_id": job.id},
                       actor_id=actor_id)
    return assignment
