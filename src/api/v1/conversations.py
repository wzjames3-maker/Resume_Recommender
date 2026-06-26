"""
智能招聘 RAG 推荐系统 - 对话管理 API 路由

/api/v1/conversations 端点
"""

from typing import List, Optional

from fastapi import APIRouter, Depends

from src.common.errors import ErrorCode, ResourceNotFoundError
from src.common.logger import get_logger
from src.common.middleware.rbac import require_permission
from src.conversation_memory.session_manager import get_session_manager
from pydantic import BaseModel, Field

logger = get_logger("api_conversations")

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


class ConversationResponse(BaseModel):
    """对话响应"""
    session_id: str = Field(..., description="会话 ID")
    user_id: str = Field(..., description="用户 ID")
    status: str = Field(..., description="会话状态")
    created_at: str = Field(..., description="创建时间")
    last_active_at: str = Field(..., description="最后活跃时间")
    turn_count: int = Field(..., description="对话轮次")


class ConversationListResponse(BaseModel):
    """对话列表响应"""
    items: List[ConversationResponse] = Field(..., description="对话列表")
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    size: int = Field(..., description="每页数量")


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    page: int = 1,
    size: int = 20,
    current_user: dict = Depends(require_permission("conversation:read")),
):
    """获取用户对话列表"""
    user_id = current_user.get("sub", "default")
    logger.info(f"获取对话列表: user_id={user_id}, page={page}, size={size}")
    session_manager = get_session_manager()
    sessions = session_manager.list_sessions(user_id, page, size)
    items = [
        ConversationResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            status=session.status.value,
            created_at=session.created_at.isoformat(),
            last_active_at=session.last_active_at.isoformat(),
            turn_count=session.turn_count,
        )
        for session in sessions
    ]
    return ConversationListResponse(items=items, total=session_manager.count_sessions(user_id) if hasattr(session_manager, "count_sessions") else len(items), page=page, size=size)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(require_permission("conversation:read")),
):
    """获取对话详情（含归属校验，admin 豁免）"""
    user_id = current_user.get("sub", "default")
    user_role = current_user.get("role", "")
    logger.info(f"获取对话详情: conversation_id={conversation_id}, user_id={user_id}")
    session_manager = get_session_manager()
    session = session_manager.get_session(conversation_id)
    if not session:
        raise ResourceNotFoundError(error_code=ErrorCode.CONV_001, detail="对话不存在")
    if session.user_id != user_id and user_role != "admin":
        raise ResourceNotFoundError(error_code=ErrorCode.CONV_001, detail="对话不存在")
    return {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "status": session.status.value,
        "created_at": session.created_at.isoformat(),
        "last_active_at": session.last_active_at.isoformat(),
        "turn_count": session.turn_count,
        "messages": [
            {"role": msg.role, "content": msg.content, "timestamp": msg.timestamp.isoformat()}
            for msg in session.messages
        ],
        "last_query": session.last_query,
    }


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(require_permission("conversation:delete")),
):
    """删除对话（含归属校验，admin 豁免）"""
    user_id = current_user.get("sub", "default")
    user_role = current_user.get("role", "")
    logger.info(f"删除对话: conversation_id={conversation_id}, user_id={user_id}")
    session_manager = get_session_manager()
    session = session_manager.get_session(conversation_id)
    if not session:
        raise ResourceNotFoundError(error_code=ErrorCode.CONV_001, detail="对话不存在")
    if session.user_id != user_id and user_role != "admin":
        raise ResourceNotFoundError(error_code=ErrorCode.CONV_001, detail="对话不存在")
    session_manager.delete_session(conversation_id)
    return {"success": True, "message": "对话已删除"}
