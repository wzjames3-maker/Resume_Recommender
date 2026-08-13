import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Conversation, Message, User, WorkspaceMember
from app.services.model_client import ModelCallError
from app.services.search.context import deserialize_context, serialize_context
from app.services.search.flow import run_search_flow

router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str = Field(..., min_length=1, max_length=4000)
    stream: bool = True


async def _ws_membership(ws_id: int, user: User, db: AsyncSession) -> WorkspaceMember:
    row = await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user.id))
    membership = row.scalar_one_or_none()
    if membership is None:
        raise HTTPException(404, "资源不存在")
    return membership


def _role_of(membership: WorkspaceMember) -> str:
    return membership.role.value if hasattr(membership.role, "value") else str(membership.role)


async def _load_context(db, conv_id: int) -> dict | None:
    """读取最近一条含 context 的 assistant 消息（拒答/闲聊轮不写 context，需回退到上一条有效 context）。"""
    rows = await db.execute(select(Message).where(
        Message.conversation_id == conv_id, Message.role == "assistant").order_by(Message.id.desc()).limit(20))
    for msg in rows.scalars().all():
        for src in msg.sources or []:
            if isinstance(src, dict) and src.get("type") == "context":
                return deserialize_context(src["payload"])
    return None


@router.post("/workspaces/{ws_id}/search-chat")
async def search_chat(ws_id: int, body: SearchChatRequest,
                      user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    membership = await _ws_membership(ws_id, user, db)
    role = _role_of(membership)

    if body.conversation_id is not None:
        conv = await db.get(Conversation, body.conversation_id)
        if conv is None or conv.user_id != user.id or conv.workspace_id != ws_id or conv.knowledge_base_id is not None:
            raise HTTPException(404, "会话不存在")
    else:
        conv = Conversation(user_id=user.id, workspace_id=ws_id, knowledge_base_id=None, title=body.message[:30])
        db.add(conv)
        await db.flush()
    db.add(Message(conversation_id=conv.id, role="user", content=body.message))
    await db.commit()

    prior = await _load_context(db, conv.id)

    async def _execute() -> dict:
        outcome = await run_search_flow(db, workspace_id=ws_id, actor_role=role, actor_id=user.id,
                                        utterance=body.message, prior_context=prior)
        sources = list(outcome.cards)
        if outcome.context is not None:
            sources.append({"type": "context", "payload": serialize_context(outcome.context)})
        msg = Message(conversation_id=conv.id, role="assistant", content=outcome.summary, sources=sources)
        db.add(msg)
        await db.commit()
        return {
            "intent": outcome.intent,
            "cards": outcome.cards,
            "summary": outcome.summary,
            "conversation_id": conv.id,
            "message_id": msg.id,
            "job_candidates": outcome.job_candidates,
            "statistics": outcome.statistics,
        }

    if not body.stream:
        try:
            payload = await _execute()
        except ModelCallError as exc:
            raise HTTPException(502, f"搜索模型调用失败：{exc}") from exc
        return {
            "intent": payload["intent"],
            "cards": payload["cards"],
            "summary": payload["summary"],
            "conversation_id": payload["conversation_id"],
            "message_id": payload["message_id"],
            "job_candidates": payload["job_candidates"],
            "statistics": payload["statistics"],
        }

    async def gen():
        try:
            payload = await _execute()
            yield f"data: {json.dumps({'type': 'intent', 'intent': payload['intent']})}\n\n"
            yield f"data: {json.dumps({'type': 'cards', 'cards': payload['cards']})}\n\n"
            if payload.get("job_candidates"):
                yield f"data: {json.dumps({'type': 'job_candidates', 'jobs': payload['job_candidates']})}\n\n"
            if payload.get("statistics"):
                yield f"data: {json.dumps({'type': 'statistics', 'statistics': payload['statistics']})}\n\n"
            yield f"data: {json.dumps({'type': 'summary', 'text': payload['summary']})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'message_id': payload['message_id'], 'conversation_id': payload['conversation_id']})}\n\n"
        except ModelCallError as exc:
            yield f"data: {json.dumps({'type': 'error', 'code': 'MODEL_ERROR', 'message': f'搜索模型调用失败：{exc}'})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'code': 'INTERNAL_ERROR', 'message': '搜人时发生错误，请稍后重试'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")