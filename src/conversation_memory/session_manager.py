"""
智能招聘 RAG 推荐系统 - 会话管理模块

会话创建/查询/删除/消息追加
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.common.logger import get_logger

logger = get_logger("session_manager")


class SessionStatus(str, Enum):
    """会话状态"""

    ACTIVE = "active"  # 活跃
    EXPIRED = "expired"  # 已过期
    DELETED = "deleted"  # 已删除


class Message(BaseModel):
    """消息"""

    role: str = Field(..., description="角色（user/assistant/system）")
    content: str = Field(..., description="消息内容")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="消息时间")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class SessionState(BaseModel):
    """会话状态"""

    session_id: str = Field(..., description="会话 ID")
    user_id: str = Field(..., description="用户 ID")
    status: SessionStatus = Field(default=SessionStatus.ACTIVE, description="会话状态")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间")
    last_active_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="最后活跃时间")

    # Slot 状态
    last_query: Optional[Dict[str, Any]] = Field(None, description="上一次查询的 Slots")
    last_filters: Optional[Dict[str, Any]] = Field(None, description="上一次生效的过滤条件")
    last_candidates: Optional[List[Dict[str, Any]]] = Field(None, description="上一次推荐的候选人")
    turn_count: int = Field(default=0, description="对话轮次")
    last_intent: Optional[str] = Field(None, description="上一次识别的意图")

    # 消息历史
    messages: List[Message] = Field(default_factory=list, description="消息历史")


class SessionManager:
    """会话管理器"""

    def __init__(self, ttl_seconds: int = 1800):
        """
        初始化会话管理器

        Args:
            ttl_seconds: 会话 TTL（秒）
        """
        self.ttl_seconds = ttl_seconds
        self._sessions: Dict[str, SessionState] = {}

    def create_session(self, user_id: str) -> SessionState:
        """
        创建会话

        Args:
            user_id: 用户 ID

        Returns:
            SessionState: 会话状态
        """
        session_id = str(uuid.uuid4())

        session = SessionState(
            session_id=session_id,
            user_id=user_id,
            status=SessionStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            last_active_at=datetime.now(timezone.utc),
        )

        self._sessions[session_id] = session

        logger.info(f"创建会话: session_id={session_id}, user_id={user_id}")

        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """
        获取会话

        Args:
            session_id: 会话 ID

        Returns:
            Optional[SessionState]: 会话状态，不存在返回 None
        """
        session = self._sessions.get(session_id)

        if not session:
            logger.warning(f"会话不存在: session_id={session_id}")
            return None

        # 检查状态
        if session.status != SessionStatus.ACTIVE:
            logger.warning(f"会话状态异常: session_id={session_id}, status={session.status}")
            return None

        # TTL 检查
        elapsed = (datetime.now(timezone.utc) - session.last_active_at).total_seconds()
        if elapsed > self.ttl_seconds:
            session.status = SessionStatus.EXPIRED
            logger.warning(f"会话已过期: session_id={session_id}, elapsed={elapsed:.0f}s")
            return None

        return session

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话

        Args:
            session_id: 会话 ID

        Returns:
            bool: 是否删除成功
        """
        session = self._sessions.get(session_id)

        if not session:
            logger.warning(f"会话不存在: session_id={session_id}")
            return False

        session.status = SessionStatus.DELETED

        logger.info(f"删除会话: session_id={session_id}")

        return True

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        追加消息

        Args:
            session_id: 会话 ID
            role: 角色
            content: 消息内容
            metadata: 元数据

        Returns:
            bool: 是否追加成功
        """
        session = self.get_session(session_id)

        if not session:
            return False

        # 创建消息
        message = Message(
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata or {},
        )

        # 追加消息
        session.messages.append(message)

        # 更新轮次
        if role == "user":
            session.turn_count += 1

        # 更新最后活跃时间
        session.last_active_at = datetime.now(timezone.utc)

        logger.info(f"追加消息: session_id={session_id}, role={role}, turn={session.turn_count}")

        return True

    def update_session_state(
        self,
        session_id: str,
        last_query: Optional[Dict[str, Any]] = None,
        last_filters: Optional[Dict[str, Any]] = None,
        last_candidates: Optional[List[Dict[str, Any]]] = None,
        last_intent: Optional[str] = None,
    ) -> bool:
        """
        更新会话状态

        Args:
            session_id: 会话 ID
            last_query: 上一次查询的 Slots
            last_filters: 上一次生效的过滤条件
            last_candidates: 上一次推荐的候选人

        Returns:
            bool: 是否更新成功
        """
        session = self.get_session(session_id)

        if not session:
            return False

        if last_query is not None:
            session.last_query = last_query

        if last_filters is not None:
            session.last_filters = last_filters

        if last_candidates is not None:
            session.last_candidates = last_candidates

        if last_intent is not None:
            session.last_intent = last_intent

        session.last_active_at = datetime.now(timezone.utc)

        logger.info(f"更新会话状态: session_id={session_id}")

        return True

    def list_sessions(
        self,
        user_id: str,
        page: int = 1,
        size: int = 20,
    ) -> List[SessionState]:
        """
        获取用户会话列表

        Args:
            user_id: 用户 ID
            page: 页码
            size: 每页数量

        Returns:
            List[SessionState]: 会话列表
        """
        # 过滤用户会话
        user_sessions = [
            session for session in self._sessions.values()
            if session.user_id == user_id and session.status == SessionStatus.ACTIVE
        ]

        # 按最后活跃时间排序
        user_sessions.sort(key=lambda s: s.last_active_at, reverse=True)

        # 分页
        start = (page - 1) * size
        end = start + size

        return user_sessions[start:end]

    def get_conversation_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取对话上下文

        Args:
            session_id: 会话 ID

        Returns:
            Optional[Dict[str, Any]]: 对话上下文
        """
        session = self.get_session(session_id)

        if not session:
            return None

        return {
            "conversation_id": session.session_id,
            "turn_count": session.turn_count,
            "last_query": session.last_query,
            "last_filters": session.last_filters,
            "last_candidates": session.last_candidates,
            "last_intent": session.last_intent,
        }


# 全局会话管理器实例
session_manager = SessionManager()


def get_session_manager() -> SessionManager:
    """获取会话管理器实例"""
    return session_manager
