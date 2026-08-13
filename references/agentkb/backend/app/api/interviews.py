from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Assignment, ModelConfig, User, WorkspaceMember
from app.services.candidate_access import CandidateAccessError, get_visible_candidate
from app.services.model_client import ModelCallError

router = APIRouter(prefix="/api/v1", tags=["interviews"])


async def _member_info(db: AsyncSession, ws_id: int, user_id: int) -> WorkspaceMember:
    row = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "资源不存在")
    return row


async def _visible_assignment(db: AsyncSession, ws_id: int, assignment_id: int, role: str) -> Assignment:
    a = await db.get(Assignment, assignment_id)
    if a is None or a.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    try:
        await get_visible_candidate(db, workspace_id=ws_id, candidate_id=a.candidate_id, role=role)
    except CandidateAccessError as exc:
        raise HTTPException(404, str(exc)) from exc
    return a


async def _get_llm(db: AsyncSession, ws_id: int):
    from app.services.crypto import decrypt_secret
    from app.services.model_client import LLMClient

    cfg = (await db.execute(select(ModelConfig).where(
        ModelConfig.workspace_id == ws_id, ModelConfig.model_type == "llm"))).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(502, "工作区未配置 LLM 模型，无法生成面试总结")
    return LLMClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


class ScheduleRoundRequest(BaseModel):
    interviewer_id: int
    scheduled_at: datetime


@router.post("/workspaces/{ws_id}/assignments/{assignment_id}/interview-rounds")
async def schedule_round_endpoint(ws_id: int, assignment_id: int, body: ScheduleRoundRequest,
                                  user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    await _visible_assignment(db, ws_id, assignment_id, membership.role.value)
    from app.services.interview_service import InterviewError, schedule_round
    try:
        r = await schedule_round(db, workspace_id=ws_id, assignment_id=assignment_id,
                                 interviewer_id=body.interviewer_id, scheduled_at=body.scheduled_at,
                                 actor_id=user.id)
    except InterviewError as exc:
        raise HTTPException(400, str(exc))
    await db.commit()
    return {"round_id": r.id, "round_no": r.round_no}


class FeedbackRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)
    conclusion: str
    comment: str = Field(..., min_length=1, max_length=2000)
    reject_reason: str | None = Field(None, max_length=256)


@router.post("/workspaces/{ws_id}/interview-rounds/{round_id}/feedback")
async def submit_feedback_endpoint(ws_id: int, round_id: int, body: FeedbackRequest,
                                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    # 先校验 round 存在且属当前工作区（避免先改后查 + 存在性侧信道）
    from app.models import InterviewRound
    pre = await db.get(InterviewRound, round_id)
    if pre is None or pre.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    await _visible_assignment(db, ws_id, pre.assignment_id, membership.role.value)
    from app.services.interview_service import InterviewError, submit_feedback
    try:
        r = await submit_feedback(db, round_id=round_id, score=body.score,
                                  conclusion=body.conclusion, comment=body.comment,
                                  actor_id=user.id, reject_reason=body.reject_reason)
    except InterviewError as exc:
        raise HTTPException(400, str(exc))
    await db.commit()
    return {"round_id": r.id, "conclusion": r.conclusion.value, "score": r.score}


class InterviewResultRequest(BaseModel):
    result: str
    reason: str | None = Field(None, max_length=256)


@router.post("/workspaces/{ws_id}/assignments/{assignment_id}/interview-result")
async def update_interview_result_endpoint(ws_id: int, assignment_id: int, body: InterviewResultRequest,
                                           user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    await _visible_assignment(db, ws_id, assignment_id, membership.role.value)
    from app.services.interview_service import InterviewError, update_interview_result

    try:
        assignment = await update_interview_result(db, workspace_id=ws_id, assignment_id=assignment_id,
                                                   result=body.result, reason=body.reason, actor_id=user.id)
    except InterviewError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return {"assignment_id": assignment.id, "interview_result": assignment.interview_result.value}


@router.post("/workspaces/{ws_id}/interview-rounds/{round_id}/summarize")
async def summarize_endpoint(ws_id: int, round_id: int,
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    from app.models import InterviewRound
    pre = await db.get(InterviewRound, round_id)
    if pre is None or pre.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    await _visible_assignment(db, ws_id, pre.assignment_id, membership.role.value)
    from app.services.interview_service import InterviewError, ai_summarize
    try:
        llm = await _get_llm(db, ws_id)
        r = await ai_summarize(db, round_id=round_id, llm=llm, actor_id=user.id)
    except InterviewError as exc:
        raise HTTPException(400, str(exc))
    except ModelCallError as exc:
        raise HTTPException(502, f"AI 总结失败：{exc}")
    await db.commit()
    return {"round_id": r.id, "ai_summary": r.ai_summary, "comment": r.comment}


@router.get("/workspaces/{ws_id}/assignments/{assignment_id}/interview-rounds")
async def list_rounds_endpoint(ws_id: int, assignment_id: int,
                               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    await _visible_assignment(db, ws_id, assignment_id, membership.role.value)
    from app.services.interview_service import list_rounds
    return {"items": await list_rounds(db, assignment_id)}


@router.get("/workspaces/{ws_id}/interviews/overdue")
async def overdue_endpoint(ws_id: int,
                           user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    from app.services.interview_service import list_overdue
    items = await list_overdue(db, workspace_id=ws_id, interviewer_id=user.id)
    return {"items": items}
