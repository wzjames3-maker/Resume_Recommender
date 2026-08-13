from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Chunk, Document, DocumentStatus, KnowledgeBase, User
from app.services.kb_service import (
    ensure_admin,
    ensure_member,
    get_kb_for_admin,
    get_kb_for_member,
    remove_storage_file,
)

router = APIRouter(prefix="/api/v1", tags=["knowledge_bases"])

class KBCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field("", max_length=512)
    embedding_model: str = Field("bge-m3", max_length=128)
    chunk_size: int = Field(512, ge=64, le=8192)
    chunk_overlap: int = Field(64, ge=0)

class KBUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, max_length=512)

class KBOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    description: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    created_at: datetime
    updated_at: datetime

class KBDetailOut(KBOut):
    doc_count: int
    chunk_count: int

def _to_out(kb: KnowledgeBase) -> KBOut:
    return KBOut(
        id=kb.id,
        workspace_id=kb.workspace_id,
        name=kb.name,
        description=kb.description,
        embedding_model=kb.embedding_model,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )

@router.post("/workspaces/{ws_id}/knowledge-bases", status_code=201)
async def create_kb(ws_id: int, body: KBCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_admin(db, ws_id, user.id)
    if body.chunk_overlap >= body.chunk_size:
        raise HTTPException(400, "chunk_overlap 必须小于 chunk_size")
    existing = await db.execute(select(KnowledgeBase).where(KnowledgeBase.workspace_id == ws_id, KnowledgeBase.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(409, "同一工作区内知识库重名")
    kb = KnowledgeBase(
        workspace_id=ws_id,
        name=body.name,
        description=body.description,
        embedding_model=body.embedding_model,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return _to_out(kb)

@router.get("/workspaces/{ws_id}/knowledge-bases")
async def list_kbs(ws_id: int, page: int = 1, page_size: int = 20, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await ensure_member(db, ws_id, user.id)
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = await db.scalar(select(func.count(KnowledgeBase.id)).where(KnowledgeBase.workspace_id == ws_id))
    rows = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.workspace_id == ws_id).order_by(KnowledgeBase.id).offset((page - 1) * page_size).limit(page_size)
    )
    return {"total": total, "page": page, "page_size": page_size, "items": [_to_out(kb) for kb in rows.scalars().all()]}

@router.get("/knowledge-bases/{kb_id}")
async def get_kb(kb_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await get_kb_for_member(db, kb_id, user)
    doc_count = await db.scalar(select(func.count(Document.id)).where(Document.knowledge_base_id == kb.id))
    chunk_count = await db.scalar(
        select(func.count(Chunk.id)).join(Document, Document.id == Chunk.document_id).where(Document.knowledge_base_id == kb.id)
    )
    return KBDetailOut(**_to_out(kb).model_dump(), doc_count=doc_count, chunk_count=chunk_count)

@router.put("/knowledge-bases/{kb_id}")
async def update_kb(kb_id: int, body: KBUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await get_kb_for_admin(db, kb_id, user)
    if body.name is not None and body.name != kb.name:
        existing = await db.execute(select(KnowledgeBase).where(KnowledgeBase.workspace_id == kb.workspace_id, KnowledgeBase.name == body.name, KnowledgeBase.id != kb.id))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(409, "同一工作区内知识库重名")
    if body.name is not None:
        kb.name = body.name
    if body.description is not None:
        kb.description = body.description
    await db.commit()
    await db.refresh(kb)
    return _to_out(kb)

@router.delete("/knowledge-bases/{kb_id}", status_code=204)
async def delete_kb(kb_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await get_kb_for_admin(db, kb_id, user)
    processing = await db.scalar(
        select(func.count(Document.id)).where(Document.knowledge_base_id == kb.id, Document.status == DocumentStatus.processing)
    )
    if processing:
        raise HTTPException(409, "知识库下存在正在解析中的文档，请稍后再试")
    rows = await db.execute(select(Document.storage_key).where(Document.knowledge_base_id == kb.id))
    storage_keys = [row[0] for row in rows.all()]
    await db.delete(kb)
    await db.commit()
    for sk in storage_keys:
        remove_storage_file(sk)