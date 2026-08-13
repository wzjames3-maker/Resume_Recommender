
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import (
    Document,
    KnowledgeBase,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.services.auth_service import get_user_by_email
from app.services.kb_service import remove_storage_file

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])

class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)

class WorkspaceOut(BaseModel):
    id: int
    name: str
    role: WorkspaceRole
    created_at: str

class WorkspaceMemberOut(BaseModel):
    user_id: int
    nickname: str
    email: str
    role: WorkspaceRole
    joined_at: str

class WorkspaceDetailOut(WorkspaceOut):
    members: list[WorkspaceMemberOut]

class MemberInviteRequest(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.member

class MemberRoleUpdateRequest(BaseModel):
    role: Literal["admin", "member"]

class WorkspaceUsageOut(BaseModel):
    tokens_used_this_month: int
    monthly_limit: int
    remaining: int


async def _get_membership(db: AsyncSession, ws_id: int, user_id: int) -> WorkspaceMember:
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))
    m = row.scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "资源不存在")
    return m


async def _member_out(db: AsyncSession, m: WorkspaceMember) -> WorkspaceMemberOut:
    user = await db.get(User, m.user_id)
    return WorkspaceMemberOut(
        user_id=m.user_id,
        nickname=user.nickname if user else "",
        email=user.email if user else "",
        role=m.role,
        joined_at=m.joined_at.isoformat(),
    )


@router.post("", status_code=201)
async def create_workspace(body: WorkspaceCreateRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ws = Workspace(name=body.name, owner_id=user.id)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner))
    await db.commit()
    await db.refresh(ws)
    return WorkspaceOut(id=ws.id, name=ws.name, role=WorkspaceRole.owner, created_at=ws.created_at.isoformat())

@router.get("")
async def list_workspaces(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
    )
    return {"items": [WorkspaceOut(id=ws.id, name=ws.name, role=role, created_at=ws.created_at.isoformat()) for ws, role in rows.all()]}

@router.get("/{ws_id}", response_model=WorkspaceDetailOut)
async def get_workspace(ws_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    me = await _get_membership(db, ws_id, user.id)
    ws = await db.get(Workspace, ws_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在或非成员")
    rows = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id).order_by(WorkspaceMember.joined_at))
    members = [await _member_out(db, m) for m in rows.scalars().all()]
    return WorkspaceDetailOut(id=ws.id, name=ws.name, role=me.role, created_at=ws.created_at.isoformat(), members=members)

@router.delete("/{ws_id}", status_code=204)
async def delete_workspace(ws_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    me = await _get_membership(db, ws_id, user.id)
    if me.role != WorkspaceRole.owner:
        raise HTTPException(403, "仅 owner 可删除工作区")
    ws = await db.get(Workspace, ws_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在或非成员")
    rows = await db.execute(
        select(Document.storage_key).join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
        .where(KnowledgeBase.workspace_id == ws_id)
    )
    storage_keys = [row[0] for row in rows.all()]
    await db.delete(ws)
    await db.commit()
    for sk in storage_keys:
        remove_storage_file(sk)

@router.post("/{ws_id}/members", status_code=201, response_model=WorkspaceMemberOut)
async def invite(ws_id: int, body: MemberInviteRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.role == WorkspaceRole.owner:
        raise HTTPException(403, "不允许直接邀请为 owner")
    inviter = await _get_membership(db, ws_id, user.id)
    if inviter.role not in ("admin", "owner"):
        raise HTTPException(403, "仅 admin 及以上可邀请成员")
    if body.role == WorkspaceRole.admin and inviter.role != WorkspaceRole.owner:
        raise HTTPException(403, "仅 owner 可邀请或提升为 admin")
    target = await get_user_by_email(db, body.email)
    if target is None:
        raise HTTPException(404, "邮箱对应账号不存在")
    existing = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == target.id))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "该用户已是工作区成员")
    m = WorkspaceMember(workspace_id=ws_id, user_id=target.id, role=body.role)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return await _member_out(db, m)

@router.patch("/{ws_id}/members/{target_user_id}", response_model=WorkspaceMemberOut)
async def update_member_role(ws_id: int, target_user_id: int, body: MemberRoleUpdateRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    operator = await _get_membership(db, ws_id, user.id)
    if operator.role not in ("admin", "owner"):
        raise HTTPException(403, "仅 admin 及以上可修改成员角色")
    target = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == target_user_id))
    m = target.scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "目标用户不是工作区成员")
    if m.role == WorkspaceRole.owner:
        raise HTTPException(409, "owner 角色不可修改")
    if body.role == WorkspaceRole.admin and operator.role != WorkspaceRole.owner:
        raise HTTPException(403, "仅 owner 可提升为 admin")
    m.role = body.role
    await db.commit()
    await db.refresh(m)
    return await _member_out(db, m)

@router.delete("/{ws_id}/members/{target_user_id}", status_code=204)
async def remove_member(ws_id: int, target_user_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    operator = await _get_membership(db, ws_id, user.id)
    if operator.role not in ("admin", "owner"):
        raise HTTPException(403, "仅 admin 及以上可移除成员")
    target = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == target_user_id))
    m = target.scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "目标用户不是工作区成员")
    if m.role == WorkspaceRole.owner:
        raise HTTPException(409, "owner 不可被移除")
    await db.delete(m)
    await db.commit()

@router.get("/{ws_id}/usage", response_model=WorkspaceUsageOut)
async def get_usage(ws_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_membership(db, ws_id, user.id)
    # M1 阶段无 token_usage 表，返回占位 0/配额；P2 用量统计接入后替换
    return WorkspaceUsageOut(tokens_used_this_month=0, monthly_limit=1_000_000, remaining=1_000_000)