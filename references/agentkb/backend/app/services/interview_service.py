from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    CandidateEventType,
    FeedbackConclusion,
    InterviewResult,
    InterviewRound,
    WorkspaceMember,
)
from app.services.candidate_lifecycle import append_event


class InterviewError(Exception):
    pass


async def _visible_round(db: AsyncSession, round_id: int) -> InterviewRound:
    r = await db.get(InterviewRound, round_id)
    if r is None:
        raise InterviewError("面试轮不存在")
    return r


async def schedule_round(db: AsyncSession, *, workspace_id: int, assignment_id: int,
                         interviewer_id: int, scheduled_at, actor_id: int) -> InterviewRound:
    """安排面试（I-1/I-6）：round_no 递增；assignment 须在 screen_passed/interviewing；面试官须为工作区成员。"""
    a = (await db.execute(select(Assignment).where(
        Assignment.id == assignment_id).with_for_update())).scalar_one_or_none()
    if a is None or a.workspace_id != workspace_id:
        raise InterviewError("指派不存在")
    if a.status not in (AssignmentStatus.screen_passed, AssignmentStatus.interviewing):
        raise InterviewError("仅初筛通过/面试中可安排面试")
    member = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == interviewer_id))).scalar_one_or_none()
    if member is None:
        raise InterviewError("面试官必须是工作区成员")
    latest = (await db.execute(select(InterviewRound).where(
        InterviewRound.assignment_id == assignment_id)
        .order_by(InterviewRound.round_no.desc()))).scalars().first()
    if a.status is AssignmentStatus.interviewing and latest is not None \
            and (latest.feedback_at is None or latest.conclusion is not FeedbackConclusion.advance
                 or latest.score is None or not latest.comment):
        raise InterviewError("上一轮反馈须为 advance 且完整才能安排下一轮")
    r = InterviewRound(workspace_id=workspace_id, assignment_id=assignment_id,
                       round_no=(latest.round_no + 1) if latest else 1,
                       interviewer_id=interviewer_id, scheduled_at=scheduled_at, created_by=actor_id)
    db.add(r)
    a.interview_result = None
    await db.flush()
    await append_event(db, candidate_id=a.candidate_id, event_type=CandidateEventType.status_changed,
                       title=f"安排第 {r.round_no} 轮面试", detail={"assignment_id": assignment_id, "round_id": r.id},
                       actor_id=actor_id)
    return r


async def submit_feedback(db: AsyncSession, *, round_id: int, score: int, conclusion: str,
                           comment: str, actor_id: int, reject_reason: str | None = None) -> InterviewRound:
    """提交反馈（I-3）：score 1-5；conclusion 枚举；history 保留旧值；feedback_at=now。"""
    r = await _visible_round(db, round_id)
    if not (isinstance(score, int) and 1 <= score <= 5):
        raise InterviewError("评分必须为 1-5")
    try:
        concl = FeedbackConclusion(conclusion)
    except ValueError:
        raise InterviewError(f"非法结论: {conclusion}") from None
    if not comment:
        raise InterviewError("评语必填")
    history = list(r.feedback_history or [])
    if r.conclusion is not None or r.score is not None:
        history.append({"score": r.score, "conclusion": r.conclusion.value if r.conclusion else None, "comment": r.comment})
    r.score, r.conclusion, r.comment = score, concl, comment
    r.feedback_history = history
    from datetime import UTC, datetime
    r.feedback_at = datetime.now(UTC)
    assignment = (await db.execute(select(Assignment).where(
        Assignment.id == r.assignment_id).with_for_update())).scalar_one()
    if concl is FeedbackConclusion.recommend:
        assignment.interview_result = InterviewResult.passed
    elif concl is FeedbackConclusion.reject:
        assignment.interview_result = InterviewResult.failed
        from app.services.assignment_service import AssignmentError, transition

        try:
            await transition(db, assignment=assignment, to_state=AssignmentStatus.rejected.value,
                             reject_reason=reject_reason, actor_id=actor_id)
        except AssignmentError as exc:
            raise InterviewError(str(exc)) from exc
    else:
        assignment.interview_result = None
    return r


async def update_interview_result(db: AsyncSession, *, workspace_id: int, assignment_id: int,
                                  result: str, actor_id: int, reason: str | None = None) -> Assignment:
    try:
        interview_result = InterviewResult(result)
    except ValueError:
        raise InterviewError(f"非法面试结果: {result}") from None
    assignment = (await db.execute(select(Assignment).where(
        Assignment.id == assignment_id, Assignment.workspace_id == workspace_id).with_for_update())).scalar_one_or_none()
    if assignment is None:
        raise InterviewError("指派不存在")
    if assignment.status not in {AssignmentStatus.pending_screen, AssignmentStatus.screen_passed,
                                 AssignmentStatus.interviewing}:
        raise InterviewError("当前招聘状态不可更新面试履约结果")
    assignment.interview_result = interview_result
    if interview_result is InterviewResult.failed:
        if not reason:
            raise InterviewError("面试不通过原因必填")
        from app.services.assignment_service import AssignmentError, transition

        try:
            await transition(db, assignment=assignment, to_state=AssignmentStatus.rejected.value,
                             reject_reason=reason, actor_id=actor_id)
        except AssignmentError as exc:
            raise InterviewError(str(exc)) from exc
    await append_event(db, candidate_id=assignment.candidate_id, event_type=CandidateEventType.status_changed,
                       title=f"面试结果：{interview_result.value}",
                       detail={"assignment_id": assignment.id, "job_id": assignment.job_id,
                               "interview_result": interview_result.value, "reason": reason},
                       actor_id=actor_id)
    return assignment


async def ai_summarize(db: AsyncSession, *, round_id: int, llm, actor_id: int) -> InterviewRound:
    """AI 总结（I-4）：评语 → {advantages, risks, suggestions}；comment 保留。"""
    r = await _visible_round(db, round_id)
    if not r.comment:
        raise InterviewError("评语为空，无法总结")
    system = "你是招聘面试反馈总结助手。把面试官自由评语归纳为结构化 JSON。输出 {\"advantages\": [...], \"risks\": [...], \"suggestions\": [...], \"reason\": \"...\"}，均为字符串数组。"
    raw = await llm.chat_json(system, r.comment, {})
    summary = {
        "advantages": raw.get("advantages") or [],
        "risks": raw.get("risks") or [],
        "suggestions": raw.get("suggestions") or [],
    }
    r.ai_summary = summary
    return r


async def list_rounds(db: AsyncSession, assignment_id: int) -> list[dict]:
    rows = (await db.execute(select(InterviewRound).where(
        InterviewRound.assignment_id == assignment_id).order_by(InterviewRound.round_no))).scalars().all()
    return [{
        "round_id": r.id, "round_no": r.round_no, "interviewer_id": r.interviewer_id,
        "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
        "score": r.score, "conclusion": r.conclusion.value if r.conclusion else None,
        "comment": r.comment, "ai_summary": r.ai_summary,
        "feedback_at": r.feedback_at.isoformat() if r.feedback_at else None,
    } for r in rows]


async def list_overdue(db: AsyncSession, *, workspace_id: int, interviewer_id: int) -> list[dict]:
    """超时待办（I-5）：当前用户为面试官、scheduled_at+48h<now 且无反馈；只读查询天然幂等。"""
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(hours=48)
    rows = (await db.execute(select(InterviewRound).where(
        InterviewRound.workspace_id == workspace_id,
        InterviewRound.interviewer_id == interviewer_id,
        InterviewRound.feedback_at.is_(None),
        InterviewRound.scheduled_at < cutoff))).scalars().all()
    return [{"round_id": r.id, "assignment_id": r.assignment_id, "round_no": r.round_no,
             "scheduled_at": r.scheduled_at.isoformat()} for r in rows]
