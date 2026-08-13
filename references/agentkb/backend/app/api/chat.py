import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import (
    Conversation,
    Document,
    KnowledgeBase,
    Message,
    User,
    WorkspaceMember,
)
from app.rag.embedder import embedder
from app.services.chat_service import build_answer
from app.services.search_service import hybrid_search

router = APIRouter(prefix="/api/v1", tags=["chat"])

class ChatRequest(BaseModel):
    knowledge_base_id: int
    conversation_id: int | None = None
    message: str = Field(..., min_length=1, max_length=4000)
    stream: bool = True

class ConversationOut(BaseModel):
    id: int
    knowledge_base_id: int
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime

class ConversationCreate(BaseModel):
    knowledge_base_id: int
    title: str | None = Field(None, max_length=128)

class MessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    token_count: int
    sources: list
    created_at: datetime


async def _kb_for_user(kb_id: int, user: User, db: AsyncSession) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == kb.workspace_id, WorkspaceMember.user_id == user.id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(404, "知识库不存在")
    return kb


async def _conv_for_user(conv_id: int, user: User, db: AsyncSession) -> Conversation:
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    kb = await db.get(KnowledgeBase, conv.knowledge_base_id)
    if kb is None:
        raise HTTPException(404, "会话不存在")
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == kb.workspace_id, WorkspaceMember.user_id == user.id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(404, "会话不存在")
    return conv


def _conv_out(conv: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conv.id,
        knowledge_base_id=conv.knowledge_base_id,
        user_id=conv.user_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )

@router.post("/conversations", status_code=201, response_model=ConversationOut)
async def create_conversation(body: ConversationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _kb_for_user(body.knowledge_base_id, user, db)
    conv = Conversation(user_id=user.id, knowledge_base_id=body.knowledge_base_id, title=body.title or "新对话")
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return _conv_out(conv)

@router.get("/conversations")
async def list_conversations(knowledge_base_id: int, page: int = 1, page_size: int = 20, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _kb_for_user(knowledge_base_id, user, db)
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    filters = [Conversation.user_id == user.id, Conversation.knowledge_base_id == knowledge_base_id]
    total = await db.scalar(select(func.count(Conversation.id)).where(*filters))
    rows = await db.execute(
        select(Conversation).where(*filters).order_by(Conversation.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_conv_out(c) for c in rows.scalars().all()],
    }

@router.get("/conversations/{conv_id}/messages")
async def list_messages(conv_id: int, page: int = 1, page_size: int = 20, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _conv_for_user(conv_id, user, db)
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = await db.scalar(select(func.count(Message.id)).where(Message.conversation_id == conv_id))
    rows = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at.asc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = [
        MessageOut(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            token_count=m.token_count,
            sources=m.sources if m.role == "assistant" else [],
            created_at=m.created_at,
        )
        for m in rows.scalars().all()
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}

@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(conv_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conv = await _conv_for_user(conv_id, user, db)
    await db.delete(conv)
    await db.commit()

async def _chunk_sources(db: AsyncSession, hits: list) -> list[dict]:
    if not hits:
        return []
    doc_ids = {h.chunk.document_id for h in hits}
    rows = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
    doc_map = {d.id: d for d in rows.scalars().all()}
    return [
        {
            "chunk_id": h.chunk.id,
            "document_id": h.chunk.document_id,
            "filename": doc_map[h.chunk.document_id].filename if h.chunk.document_id in doc_map else None,
            "content": h.chunk.content[:200],
            "score": h.score,
        }
        for h in hits
        if h.chunk.document_id in doc_map
    ]


@router.post("/chat")
async def chat(body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await _kb_for_user(body.knowledge_base_id, user, db)

    if body.conversation_id is not None:
        conv = await db.get(Conversation, body.conversation_id)
        if conv is None or conv.user_id != user.id or conv.knowledge_base_id != kb.id:
            raise HTTPException(404, "会话不存在")
    else:
        conv = Conversation(user_id=user.id, knowledge_base_id=kb.id, title=body.message[:30])
        db.add(conv)
        await db.flush()
    conv.updated_at = datetime.now(UTC)
    db.add(Message(conversation_id=conv.id, role="user", content=body.message))
    await db.commit()

    async def _make_answer() -> tuple[list, str]:
        qv = (await embedder.embed([body.message]))[0]
        hits = await hybrid_search(db, kb.id, qv, body.message, top_k=5)
        return hits, await build_answer(body.message, hits)

    if not body.stream:
        hits, answer = await _make_answer()
        sources = await _chunk_sources(db, hits)
        msg = Message(conversation_id=conv.id, role="assistant", content=answer, sources=sources)
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return {
            "answer": answer,
            "sources": sources,
            "token_count": len(answer),
            "conversation_id": conv.id,
            "message_id": msg.id,
        }

    async def gen():
        try:
            hits, answer = await _make_answer()
            sources = await _chunk_sources(db, hits)
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"
            msg = Message(conversation_id=conv.id, role="assistant", content=answer, sources=sources)
            db.add(msg)
            await db.commit()
            yield f"data: {json.dumps({'type': 'done', 'message_id': msg.id, 'token_count': len(answer), 'conversation_id': conv.id})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'code': 'INTERNAL_ERROR', 'message': '生成回答时发生错误，请稍后重试'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")