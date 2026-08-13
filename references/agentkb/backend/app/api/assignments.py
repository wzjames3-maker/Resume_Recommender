from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Assignment, Candidate, Job, User, WorkspaceMember
from app.services.assignment_service import (
    AssignmentError,
    create_assignment,
    transition,
)
from app.services.candidate_access import (
    VISIBLE_SCOPES_BY_ROLE,
    CandidateAccessError,
    get_visible_candidate,
)

router = APIRouter(prefix="/api/v1", tags=["assignments"])


async def _member_info(db: AsyncSession, ws_id: int, user_id: int) -> WorkspaceMember:
    row = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "资源不存在")
    return row


def _role_of(membership: WorkspaceMember) -> str:
    return membership.role.value if hasattr(membership.role, "value") else str(membership.role)


async def _visible_job(db: AsyncSession, ws_id: int, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None or job.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    return job


async def _visible_assignment(db: AsyncSession, ws_id: int, assignment_id: int) -> Assignment:
    a = await db.get(Assignment, assignment_id)
    if a is None or a.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    return a


class AssignRequest(BaseModel):
    candidate_id: int
    idempotency_key: str | None = Field(None, max_length=64)


class BatchAssignRequest(BaseModel):
    candidate_ids: list[int]
    idempotency_key: str | None = Field(None, max_length=64)


@router.post("/workspaces/{ws_id}/jobs/{job_id}/assignments")
async def assign_one(ws_id: int, job_id: int, body: AssignRequest,
                     user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    await _visible_job(db, ws_id, job_id)
    try:
        await get_visible_candidate(db, workspace_id=ws_id, candidate_id=body.candidate_id,
                                    role=_role_of(membership))
    except CandidateAccessError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        a = await create_assignment(db, workspace_id=ws_id, candidate_id=body.candidate_id,
                                    job_id=job_id, idempotency_key=body.idempotency_key, actor_id=user.id)
    except AssignmentError as exc:
        raise HTTPException(400, str(exc))
    from app.services.audit import add_event
    await add_event(db, action="assignment.created", result="success", resource_type="assignment",
                    resource_id=str(a.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"candidate_id": a.candidate_id, "job_id": job_id})
    await db.commit()
    return {"assignment_id": a.id, "candidate_id": a.candidate_id, "job_id": a.job_id, "status": a.status.value}


@router.post("/workspaces/{ws_id}/jobs/{job_id}/assignments/batch")
async def assign_batch(ws_id: int, job_id: int, body: BatchAssignRequest,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    await _visible_job(db, ws_id, job_id)
    role = _role_of(membership)
    items = []
    for cid in body.candidate_ids:
        # 批次级幂等：同一批命令重复提交不重复创建；key 按候选人派生避免同批内部互相去重，截断防超列宽
        derived_key = f"{body.idempotency_key}:{cid}"[:64] if body.idempotency_key else None
        try:
            await get_visible_candidate(db, workspace_id=ws_id, candidate_id=cid, role=role)
            a = await create_assignment(db, workspace_id=ws_id, candidate_id=cid, job_id=job_id,
                                        idempotency_key=derived_key, actor_id=user.id)
            items.append({"candidate_id": cid, "assignment_id": a.id, "status": a.status.value})
        except (AssignmentError, CandidateAccessError) as exc:
            items.append({"candidate_id": cid, "error": str(exc)})
    from app.services.audit import add_event
    await add_event(db, action="assignment.batch_created", result="success", resource_type="assignment",
                    workspace_id=ws_id, actor_id=user.id,
                    payload={"job_id": job_id, "count": len([i for i in items if "error" not in i])})
    await db.commit()
    return {"job_id": job_id, "items": items}


@router.get("/workspaces/{ws_id}/jobs/{job_id}/board")
async def job_board(ws_id: int, job_id: int,
                    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    job = await _visible_job(db, ws_id, job_id)
    rows = (await db.execute(select(Assignment, Candidate).join(
        Candidate, Candidate.id == Assignment.candidate_id).where(
        Assignment.workspace_id == ws_id, Assignment.job_id == job_id))).all()
    from app.models import InterviewRound
    assignment_ids = [a.id for a, _ in rows]
    round_rows = []
    if assignment_ids:
        round_rows = (await db.execute(select(InterviewRound.assignment_id, InterviewRound.feedback_at).where(
            InterviewRound.assignment_id.in_(assignment_ids)))).all()
    round_flags: dict[int, tuple[bool, bool]] = {}
    for assignment_id, feedback_at in round_rows:
        pending, completed = round_flags.get(assignment_id, (False, False))
        round_flags[assignment_id] = (pending or feedback_at is None, completed or feedback_at is not None)
    groups: dict[str, list] = {}
    for a, cand in rows:
        if cand.status not in VISIBLE_SCOPES_BY_ROLE.get(_role_of(membership), set()):
            continue
        groups.setdefault(a.status.value, []).append({
            "assignment_id": a.id, "candidate_id": cand.id, "name": cand.name,
            "status": a.status.value, "reject_reason": a.reject_reason,
            "interview_result": a.interview_result.value if a.interview_result else None,
            "has_pending_interview": round_flags.get(a.id, (False, False))[0],
            "has_completed_interview": round_flags.get(a.id, (False, False))[1],
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        })
    return {"job_id": job_id, "job_name": job.name, "groups": groups}


@router.get("/workspaces/{ws_id}/candidates/{candidate_id}/assignments")
async def candidate_assignments(ws_id: int, candidate_id: int,
                                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    try:
        await get_visible_candidate(db, workspace_id=ws_id, candidate_id=candidate_id,
                                    role=_role_of(membership))
    except CandidateAccessError as exc:
        raise HTTPException(404, str(exc)) from exc
    rows = (await db.execute(select(Assignment, Job).join(
        Job, Job.id == Assignment.job_id).where(
        Assignment.workspace_id == ws_id, Assignment.candidate_id == candidate_id)
        .order_by(Assignment.id.desc()))).all()
    return {"items": [{"assignment_id": a.id, "job_id": j.id, "job_name": j.name,
                       "status": a.status.value, "reject_reason": a.reject_reason,
                       "interview_result": a.interview_result.value if a.interview_result else None,
                       "updated_at": a.updated_at.isoformat() if a.updated_at else None}
                      for a, j in rows]}

class TransitionRequest(BaseModel):
    to_state: str
    reject_reason: str | None = Field(None, max_length=256)
    close_reason: str | None = Field(None, max_length=256)


@router.post("/workspaces/{ws_id}/assignments/{assignment_id}/transition")
async def transition_assignment(ws_id: int, assignment_id: int, body: TransitionRequest,
                                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    role = _role_of(membership)
    a = await _visible_assignment(db, ws_id, assignment_id)
    if body.to_state == "closed_by_job" and role not in ("admin", "owner"):
        raise HTTPException(403, "仅管理员可关闭余下指派")
    try:
        a = await transition(db, assignment=a, to_state=body.to_state,
                             reject_reason=body.reject_reason, close_reason=body.close_reason,
                             actor_id=user.id)
    except AssignmentError as exc:
        raise HTTPException(400, str(exc))
    from app.services.audit import add_event
    await add_event(db, action="assignment.transitioned", result="success", resource_type="assignment",
                    resource_id=str(a.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"to_state": a.status.value})
    await db.commit()
    return {"assignment_id": a.id, "status": a.status.value}


@router.post("/workspaces/{ws_id}/assignments/{assignment_id}/hire")
async def hire_assignment(ws_id: int, assignment_id: int,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    a = await _visible_assignment(db, ws_id, assignment_id)
    from app.services.assignment_service import hire
    try:
        a = await hire(db, assignment=a, actor_id=user.id)
    except AssignmentError as exc:
        raise HTTPException(400, str(exc))
    from app.services.audit import add_event
    await add_event(db, action="assignment.hired", result="success", resource_type="assignment",
                    resource_id=str(a.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"candidate_id": a.candidate_id})
    await db.commit()
    return {"assignment_id": a.id, "status": a.status.value}
