import logging

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import (
    Candidate,
    CandidateEventType,
    CandidateOverride,
    CandidateRevision,
    CandidateStatus,
    ResumeFile,
    ResumeIR,
    User,
    WorkspaceMember,
)
from app.services.candidate_lifecycle import append_event
from app.services.candidate_view import build_effective_view, get_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["candidates"])

MEMBER_VISIBLE = {"active", "pending_review", "rejected"}
ADMIN_VISIBLE = {"active", "pending_review", "rejected", "hired"}


async def _member_info(db: AsyncSession, ws_id: int, user_id: int) -> WorkspaceMember:
    row = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "资源不存在")
    return row


def _role_of(membership: WorkspaceMember) -> str:
    return membership.role.value if hasattr(membership.role, "value") else str(membership.role)


def _visible_scopes(role: str) -> set[str]:
    return ADMIN_VISIBLE if role in ("admin", "owner") else MEMBER_VISIBLE


async def _visible_candidate(db: AsyncSession, ws_id: int, candidate_id: int, user: User,
                             *, allow_deleted: bool = False) -> Candidate:
    membership = await _member_info(db, ws_id, user.id)
    role = _role_of(membership)
    cand = await db.get(Candidate, candidate_id)
    if cand is None or cand.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    if cand.status.value == "deleted" and not allow_deleted:
        raise HTTPException(404, "资源不存在")
    if allow_deleted and cand.status.value == "deleted":
        return cand
    if cand.status.value not in _visible_scopes(role):
        raise HTTPException(404, "资源不存在")
    return cand


@router.get("/workspaces/{ws_id}/candidates")
async def list_candidates(ws_id: int, status: str | None = None, skills: str | None = None,
                          city: str | None = None, years_min: int | None = None,
                          degree_at_least: str | None = None, level: str | None = None,
                          domain: str | None = None, source_channel: str | None = None,
                           referrer: str | None = None,
                           interview_result: str | None = None,
                           include_deleted: bool = False, page: int = 1, page_size: int = 20,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.candidate_list import list_candidates as _list

    membership = await _member_info(db, ws_id, user.id)
    role = _role_of(membership)
    scopes = _visible_scopes(role)
    if include_deleted:
        scopes = scopes | {"deleted"}
    if status:
        if status not in scopes:
            raise HTTPException(404, "资源不存在")
        scopes = {status}
    if interview_result not in (None, "passed", "failed", "no_show"):
        raise HTTPException(400, "非法面试状态")
    total, items = await _list(db, ws_id, scopes=scopes,
                               skills=skills.split(",") if skills else None, city=city,
                               years_min=years_min, degree_at_least=degree_at_least,
                               level=level, domain=domain, source_channel=source_channel,
                               referrer=referrer,
                               interview_result=interview_result,
                               page=page, page_size=page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/workspaces/{ws_id}/candidates/{candidate_id}")
async def get_candidate(ws_id: int, candidate_id: int,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _visible_candidate(db, ws_id, candidate_id, user)
    view = await build_effective_view(db, candidate_id)
    rf = (await db.execute(select(ResumeFile).where(ResumeFile.candidate_id == candidate_id)
                           .order_by(ResumeFile.id.desc()).limit(1))).scalar_one_or_none()
    ir = None
    if rf:
        ir_row = (await db.execute(select(ResumeIR).where(ResumeIR.run_id == rf.run_id))).scalar_one_or_none()
        if ir_row:
            from app.services.resume.ir_storage import decrypt_resume_ir

            try:
                ir = decrypt_resume_ir(ir_row)
            except (ValueError, InvalidTag):
                logger.error("IR 解密失败", extra={"run_id": ir_row.run_id})
                raise HTTPException(500, "IR 内容不可读取") from None
    from app.services.job_matcher import suitable_jobs_for_candidate
    suitable_jobs = await suitable_jobs_for_candidate(db, ws_id, view["fields"], view["profile"])
    from app.models import ParseRun
    source_channel = referrer = None
    if rf:
        run = (await db.execute(select(ParseRun).where(ParseRun.run_id == rf.run_id))).scalar_one_or_none()
        if run is not None:
            source_channel, referrer = run.source_channel, run.referrer
    return {"candidate": view, "ir": ir, "suitable_jobs": suitable_jobs,
            "source_channel": source_channel, "referrer": referrer}


class OverrideRequest(BaseModel):
    base_revision_id: int
    field_path: str
    action: str  # override / clear
    after_value: object | None = None


_SCALAR_FIELDS = {"name", "gender", "birth_month", "phone", "email", "highest_degree",
                  "hometown", "political_status", "expected_position", "city", "expected_city"}
_ARRAY_FIELDS = {"education", "work", "project", "skills"}


def _validate_override_path(field_path: str) -> str:
    """override 路径按 Schema 校验：顶层字段须在 KNOWN_FIELDS；标量字段禁止嵌套子路径。"""
    from app.services.candidate_view import _parse_path
    from app.services.resume.schema import KNOWN_FIELDS

    try:
        tokens = _parse_path(field_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    top = tokens[0][1]
    if not isinstance(top, str) or top not in KNOWN_FIELDS:
        raise HTTPException(400, f"非法字段路径: {field_path}")
    if len(tokens) > 1:
        if top in _SCALAR_FIELDS:
            raise HTTPException(400, f"标量字段 {top} 不可嵌套子路径")
        if top not in _ARRAY_FIELDS:
            raise HTTPException(400, f"非法数组字段路径: {field_path}")
    return field_path


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/fields")
async def override_field(ws_id: int, candidate_id: int, body: OverrideRequest,
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cand = await _visible_candidate(db, ws_id, candidate_id, user)
    if body.action not in ("override", "clear"):
        raise HTTPException(400, "action 必须为 override/clear")
    _validate_override_path(body.field_path)
    if cand.latest_revision_id != body.base_revision_id:
        raise HTTPException(409, "候选人已被重新解析，请刷新后重试")
    view = await build_effective_view(db, candidate_id)
    before = get_path(view["fields"], body.field_path)
    if body.field_path in ("phone", "email"):
        # PII 只能进 AES-GCM 列与 hash，不得写入 JSON override 明文（B-4）
        from app.services.crypto import encrypt_secret
        from app.services.resume.ingest import identity_hashes

        if body.action == "clear":
            setattr(cand, f"{body.field_path}_enc", None)
            setattr(cand, f"{body.field_path}_hash", None)
        elif isinstance(body.after_value, str):
            setattr(cand, f"{body.field_path}_enc", encrypt_secret(body.after_value))
            setattr(cand, f"{body.field_path}_hash", identity_hashes(
                body.after_value if body.field_path == "phone" else None,
                body.after_value if body.field_path == "email" else None)[0 if body.field_path == "phone" else 1])
        else:
            raise HTTPException(400, f"{body.field_path} 修正值必须为字符串")
        await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.field_override,
                           title=f"字段修正 {body.field_path}",
                           detail={"field_path": body.field_path, "action": body.action}, actor_id=user.id)
        await db.commit()
        return {"fields": view["fields"]}
    rev = (await db.execute(select(CandidateRevision).where(
        CandidateRevision.id == cand.latest_revision_id))).scalar_one()
    db.add(CandidateOverride(candidate_id=candidate_id, revision_id=rev.revision_id,
                             field_path=body.field_path, before_value=before,
                             after_value=body.after_value, action=body.action, actor_id=user.id))
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.field_override,
                       title=f"字段修正 {body.field_path}",
                       detail={"field_path": body.field_path, "action": body.action}, actor_id=user.id)
    await db.commit()
    view2 = await build_effective_view(db, candidate_id)
    return {"fields": view2["fields"]}


class MergeRequest(BaseModel):
    duplicate_id: int
    base_revision_id: int


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/merge")
async def merge_candidate(ws_id: int, candidate_id: int, body: MergeRequest,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.audit import add_event
    from app.services.candidate_merge import (
        MergeConflictError,
        MergeError,
        merge_candidates,
    )

    primary = await _visible_candidate(db, ws_id, candidate_id, user)
    absorbed = await _visible_candidate(db, ws_id, body.duplicate_id, user)
    try:
        await merge_candidates(db, primary=primary, absorbed=absorbed,
                               base_revision_id=body.base_revision_id, actor_id=user.id)
    except MergeConflictError as exc:
        raise HTTPException(409, str(exc))
    except MergeError as exc:
        raise HTTPException(400, str(exc))
    await add_event(db, action="candidate.merged", result="success", resource_type="candidate",
                    resource_id=str(primary.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"absorbed_id": absorbed.id})
    await db.commit()
    return {"candidate_id": primary.id, "absorbed_id": absorbed.id, "status": "merged"}


@router.delete("/workspaces/{ws_id}/candidates/{candidate_id}")
async def soft_delete(ws_id: int, candidate_id: int,
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from datetime import UTC, datetime, timedelta

    from app.models import Assignment, AssignmentStatus

    cand = await _visible_candidate(db, ws_id, candidate_id, user)
    if cand.status is CandidateStatus.hired:
        raise HTTPException(409, "入职员工不可删除")
    if cand.status is CandidateStatus.deleted:
        raise HTTPException(409, "候选人已删除")
    IN_PROGRESS = {AssignmentStatus.pending_screen, AssignmentStatus.screen_passed,
                   AssignmentStatus.interviewing, AssignmentStatus.offer}
    active_assign = (await db.execute(select(Assignment).where(
        Assignment.candidate_id == candidate_id,
        Assignment.workspace_id == ws_id,
        Assignment.status.in_(IN_PROGRESS)))).scalar_one_or_none()
    if active_assign is not None:
        raise HTTPException(409, "候选人有进行中指派，请先完成合法关闭或终态处理")
    cand.status = CandidateStatus.deleted
    cand.deleted_until = datetime.now(UTC) + timedelta(days=30)
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.status_changed,
                       title="软删除", detail={"to": "deleted"}, actor_id=user.id)
    await db.commit()
    return {"candidate_id": candidate_id, "status": "deleted",
            "deleted_until": cand.deleted_until.isoformat()}


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/restore")
async def restore_candidate(ws_id: int, candidate_id: int,
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.assignment_service import recompute_candidate_pool

    cand = await _visible_candidate(db, ws_id, candidate_id, user, allow_deleted=True)
    if cand.status is not CandidateStatus.deleted:
        raise HTTPException(409, "仅已删除候选人可恢复")
    cand.status = CandidateStatus.active
    cand.deleted_until = None
    await recompute_candidate_pool(db, candidate_id)
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.restored,
                       title="恢复", actor_id=user.id)
    await db.commit()
    return {"candidate_id": candidate_id, "status": "active"}


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/purge")
async def purge_candidate(ws_id: int, candidate_id: int,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    import hashlib
    import os
    from datetime import UTC, datetime

    from app.models import ResumeFile
    from app.services.audit import add_event

    cand = await _visible_candidate(db, ws_id, candidate_id, user, allow_deleted=True)
    if cand.status is not CandidateStatus.deleted:
        raise HTTPException(409, "仅已删除候选人可硬删除")
    if cand.deleted_until is not None and datetime.now(UTC) < cand.deleted_until:
        raise HTTPException(409, "30 天保留期内不可硬删除，可先恢复")
    # 物理文件批量删除（best-effort，缺失不阻断）
    files = (await db.execute(select(ResumeFile).where(
        ResumeFile.candidate_id == candidate_id))).scalars().all()
    for f in files:
        try:
            os.remove(f.storage_key)
        except OSError:
            pass
    await add_event(db, action="candidate.purged", result="success", resource_type="candidate",
                    resource_id=str(candidate_id), workspace_id=ws_id, actor_id=user.id,
                    payload={"search_text_hash": hashlib.sha256((cand.search_text or "").encode("utf-8")).hexdigest()})
    await db.delete(cand)  # FK CASCADE 级联 revision/override/嵌入/文件/事件
    await db.commit()
    return {"candidate_id": candidate_id, "status": "purged"}


@router.get("/workspaces/{ws_id}/candidates/{candidate_id}/timeline")
async def get_timeline(ws_id: int, candidate_id: int,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _visible_candidate(db, ws_id, candidate_id, user)
    from app.models import CandidateEvent

    rows = await db.execute(select(CandidateEvent).where(CandidateEvent.candidate_id == candidate_id)
                            .order_by(CandidateEvent.created_at.desc()).limit(200))
    return {"items": [{"event_type": e.event_type, "title": e.title, "detail": e.detail,
                       "actor_id": e.actor_id, "created_at": e.created_at.isoformat()}
                      for e in rows.scalars().all()]}


class NoteRequest(BaseModel):
    content: str


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/notes")
async def add_note(ws_id: int, candidate_id: int, body: NoteRequest,
                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _visible_candidate(db, ws_id, candidate_id, user)
    if not body.content or len(body.content) > 2000:
        raise HTTPException(400, "备注内容 1-2000 字符")
    # title 列 String(256)，超长截断展示；完整内容存 detail（C-1 修复）
    title = f"备注：{body.content}"[:200]
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.note,
                       title=title, detail={"content": body.content}, actor_id=user.id)
    await db.commit()
    return {"candidate_id": candidate_id}
