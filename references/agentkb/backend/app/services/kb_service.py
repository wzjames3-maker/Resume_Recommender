import logging
import os

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, KnowledgeBase, User, WorkspaceMember

logger = logging.getLogger(__name__)


def remove_storage_file(storage_key: str) -> None:
    if not storage_key:
        return
    try:
        os.remove(storage_key)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("删除物理文件失败: %s (%s)", storage_key, exc)


async def ensure_member(db: AsyncSession, ws_id: int, user_id: int) -> None:
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(404, "资源不存在")

async def ensure_admin(db: AsyncSession, ws_id: int, user_id: int) -> None:
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))
    m = row.scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "资源不存在")
    if m.role not in ("admin", "owner"):
        raise HTTPException(403, "需要 admin 及以上")

async def get_kb_for_member(db: AsyncSession, kb_id: int, user: User) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "资源不存在")
    await ensure_member(db, kb.workspace_id, user.id)
    return kb

async def get_kb_for_admin(db: AsyncSession, kb_id: int, user: User) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "资源不存在")
    await ensure_admin(db, kb.workspace_id, user.id)
    return kb

async def get_doc_for_member(db: AsyncSession, doc_id: int, user: User) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "资源不存在")
    kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
    if kb is None:
        raise HTTPException(404, "资源不存在")
    await ensure_member(db, kb.workspace_id, user.id)
    return doc

async def get_doc_for_admin(db: AsyncSession, doc_id: int, user: User) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "资源不存在")
    kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
    if kb is None:
        raise HTTPException(404, "资源不存在")
    await ensure_admin(db, kb.workspace_id, user.id)
    return doc