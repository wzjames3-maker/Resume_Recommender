"""
智能招聘 RAG 推荐系统 - Chat API 路由

/api/v1/chat 端点，支持 SSE Streaming
"""

import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.common.middleware.rbac import require_permission
from src.common.logger import get_logger
from src.conversation_memory.workflow import get_recruitment_workflow
from src.intent_router.classifier import get_intent_classifier
from src.intent_router.fallback_handler import get_intent_fallback_handler
from src.intent_router.schemas import ConversationContext, IntentEnum

logger = get_logger("api_chat")

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    """Chat 请求"""

    message: str = Field(..., description="用户消息")
    conversation_id: Optional[str] = Field(None, description="会话 ID（可选）")
    filters: Optional[dict] = Field(None, description="过滤条件（可选）")


class ChatResponse(BaseModel):
    """Chat 响应"""

    type: str = Field(..., description="事件类型")
    content: Optional[str] = Field(None, description="内容")
    data: Optional[dict] = Field(None, description="数据")


async def generate_sse_stream(
    message: str,
    conversation_id: Optional[str],
    user_id: str,
) -> AsyncGenerator[str, None]:
    """
    生成 SSE 流
    """
    import asyncio

    try:
        # 1. 意图识别（同步调用，包装到线程避免阻塞事件循环）
        classifier = get_intent_classifier()

        # 获取对话上下文
        context = None
        if conversation_id:
            from src.conversation_memory.session_manager import get_session_manager
            session_manager = get_session_manager()
            context_data = session_manager.get_conversation_context(conversation_id)
            if context_data:
                context = ConversationContext(**context_data)

        intent_result = await asyncio.to_thread(classifier.classify, message, context)

        # 2. Fallback 检查
        fallback_handler = get_intent_fallback_handler()
        fallback_response = fallback_handler.handle(intent_result)

        if fallback_response.is_fallback:
            # 发送 Fallback 响应
            yield f"data: {json.dumps({'type': 'token', 'content': fallback_response.message}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'content': ''}, ensure_ascii=False)}\n\n"
            return

        # 3. 执行工作流
        workflow = get_recruitment_workflow()

        INTENT_HANDLERS = {
            IntentEnum.RECRUITMENT_SEARCH: lambda: workflow.search(intent_result, conversation_id, user_id),
            IntentEnum.RECRUITMENT_REFINE: lambda: workflow.refine(intent_result, conversation_id) if conversation_id else None,
            IntentEnum.CANDIDATE_LOOKUP: lambda: workflow.lookup(intent_result, conversation_id),
        }

        FALLBACK_MESSAGES = {
            IntentEnum.RESUME_UPLOAD: "请使用简历上传功能上传简历文件（支持 PDF/DOCX/JSON 格式）。",
            IntentEnum.RESUME_MANAGE: "您可以在简历管理页面查看和编辑已上传的简历。",
            IntentEnum.KNOWLEDGE_QA: "关于招聘相关问题，您可以咨询招聘流程、面试技巧、人才评估标准等。",
            IntentEnum.ANALYTICS: "数据统计功能正在开发中，敬请期待。",
            IntentEnum.CHAT: "您好！我是智能招聘助手，可以帮您搜索候选人、查看简历详情、对比候选人等。",
            IntentEnum.RECRUITMENT_COMPARE: "候选人对比功能正在开发中，您可以先查看单个候选人详情。",
        }
        DEFAULT_FALLBACK = "您好！我是智能招聘助手，请问有什么可以帮您？"

        handler = INTENT_HANDLERS.get(intent_result.intent)
        if handler:
            if intent_result.intent == IntentEnum.RECRUITMENT_REFINE and not conversation_id:
                yield f"data: {json.dumps({'type': 'error', 'message': '请先进行搜索'}, ensure_ascii=False)}\n\n"
                return
            result = await asyncio.to_thread(handler)
        else:
            msg = FALLBACK_MESSAGES.get(intent_result.intent, DEFAULT_FALLBACK)
            yield f"data: {json.dumps({'type': 'token', 'content': msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'content': ''}, ensure_ascii=False)}\n\n"
            return

        # 4. 发送响应
        if result.success:
            # 发送消息
            yield f"data: {json.dumps({'type': 'token', 'content': result.message}, ensure_ascii=False)}\n\n"

            # 发送候选人列表
            if result.candidates:
                yield f"data: {json.dumps({'type': 'sources', 'candidates': result.candidates}, ensure_ascii=False)}\n\n"

            # 发送完成标记
            yield f"data: {json.dumps({'type': 'done', 'session_id': result.session_id}, ensure_ascii=False)}\n\n"
        else:
            # 发送错误
            yield f"data: {json.dumps({'type': 'error', 'message': result.message}, ensure_ascii=False)}\n\n"

    except Exception as e:
        logger.error(f"SSE 流生成失败: {str(e)}")
        yield f"data: {json.dumps({'type': 'error', 'message': '内部错误'}, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: dict = Depends(require_permission("conversation:create")),
):
    """
    Chat 端点

    支持 SSE Streaming 响应
    """
    user_id = current_user.get("sub", "default")

    logger.info(f"收到 Chat 请求: user_id={user_id}, message={request.message[:50]}...")

    return StreamingResponse(
        generate_sse_stream(
            message=request.message,
            conversation_id=request.conversation_id,
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
