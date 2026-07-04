"""
智能招聘 RAG 推荐系统 - 会话管理模块

会话创建/查询/删除/消息追加
支持内存存储（dev/test）和 Redis 存储（production）
"""

import json
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

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> "SessionState":
        return cls.model_validate(json.loads(data))


class _RedisSessionBackend:
    """Redis 会话后端"""

    _REDIS_KEY_PREFIX = "session:"
    _USER_INDEX_PREFIX = "session:user:"

    def __init__(self, ttl_seconds: int = 1800):
        self.ttl_seconds = ttl_seconds
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            from src.common.config import get_settings
            settings = get_settings()
            import redis
            self._redis = redis.from_url(
                settings.redis.redis_url,
                decode_responses=True,
            )
        return self._redis

    def _save(self, session: SessionState) -> None:
        redis = self._get_redis()
        key = f"{self._REDIS_KEY_PREFIX}{session.session_id}"
        redis.setex(key, self.ttl_seconds, session.to_json())
        redis.sadd(f"{self._USER_INDEX_PREFIX}{session.user_id}", session.session_id)

    def _load(self, session_id: str) -> Optional[SessionState]:
        redis = self._get_redis()
        key = f"{self._REDIS_KEY_PREFIX}{session_id}"
        data = redis.get(key)
        if data is None:
            return None
        return SessionState.from_json(data)

    def _delete(self, session_id: str) -> None:
        redis = self._get_redis()
        key = f"{self._REDIS_KEY_PREFIX}{session_id}"
        redis.delete(key)

    def _count_user_sessions(self, user_id: str) -> int:
        redis = self._get_redis()
        return redis.scard(f"{self._USER_INDEX_PREFIX}{user_id}")


class SessionManager:
    """会话管理器（自动选择内存或 Redis 后端）"""

    def __init__(self, ttl_seconds: int = 1800):
        self.ttl_seconds = ttl_seconds
        self._sessions: Dict[str, SessionState] = {}
        self._redis_backend: Optional[_RedisSessionBackend] = None

    def _use_redis(self) -> bool:
        try:
            from src.common.config import Environment, get_settings
            return get_settings().app.APP_ENV == Environment.PROD
        except Exception:
            return False

    def _get_redis(self) -> Optional[_RedisSessionBackend]:
        if not self._use_redis():
            return None
        if self._redis_backend is None:
            self._redis_backend = _RedisSessionBackend(ttl_seconds=self.ttl_seconds)
        return self._redis_backend

    def create_session(self, user_id: str) -> SessionState:
        session_id = str(uuid.uuid4())
        session = SessionState(
            session_id=session_id,
            user_id=user_id,
            status=SessionStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            last_active_at=datetime.now(timezone.utc),
        )
        redis = self._get_redis()
        if redis:
            try:
                redis._save(session)
            except Exception as e:
                logger.warning(f"Redis session save failed, falling back to memory: {e}")
                self._sessions[session_id] = session
        else:
            self._sessions[session_id] = session

        logger.info(f"创建会话: session_id={session_id}, user_id={user_id}")
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        redis = self._get_redis()
        if redis:
            try:
                session = redis._load(session_id)
                if session:
                    if session.status != SessionStatus.ACTIVE:
                        return None
                    return session
            except Exception as e:
                logger.warning(f"Redis session load failed, falling back to memory: {e}")

        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"会话不存在: session_id={session_id}")
            return None
        if session.status != SessionStatus.ACTIVE:
            logger.warning(f"会话状态异常: session_id={session_id}, status={session.status}")
            return None
        elapsed = (datetime.now(timezone.utc) - session.last_active_at).total_seconds()
        if elapsed > self.ttl_seconds:
            session.status = SessionStatus.EXPIRED
            logger.warning(f"会话已过期: session_id={session_id}, elapsed={elapsed:.0f}s")
            return None
        return session

    def delete_session(self, session_id: str) -> bool:
        redis = self._get_redis()
        if redis:
            try:
                redis._delete(session_id)
                logger.info(f"删除会话: session_id={session_id}")
                return True
            except Exception as e:
                logger.warning(f"Redis session delete failed: {e}")

        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"会话不存在: session_id={session_id}")
            return False
        session.status = SessionStatus.DELETED
        logger.info(f"删除会话: session_id={session_id}")
        return True

    def append_message(self, session_id: str, role: str, content: str,
                       metadata: Optional[Dict[str, Any]] = None) -> bool:
        session = self.get_session(session_id)
        if not session:
            return False
        message = Message(
            role=role, content=content,
            timestamp=datetime.now(timezone.utc), metadata=metadata or {},
        )
        session.messages.append(message)
        if role == "user":
            session.turn_count += 1
        session.last_active_at = datetime.now(timezone.utc)
        self._persist(session_id, session)
        logger.info(f"追加消息: session_id={session_id}, role={role}, turn={session.turn_count}")
        return True

    def update_session_state(self, session_id: str,
                             last_query: Optional[Dict[str, Any]] = None,
                             last_filters: Optional[Dict[str, Any]] = None,
                             last_candidates: Optional[List[Dict[str, Any]]] = None,
                             last_intent: Optional[str] = None) -> bool:
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
        self._persist(session_id, session)
        logger.info(f"更新会话状态: session_id={session_id}")
        return True

    def _persist(self, session_id: str, session: SessionState) -> None:
        redis = self._get_redis()
        if redis:
            try:
                redis._save(session)
                return
            except Exception as e:
                logger.warning(f"Redis persist failed: {e}")
        self._sessions[session_id] = session

    def list_sessions(self, user_id: str, page: int = 1, size: int = 20) -> List[SessionState]:
        redis = self._get_redis()
        if redis:
            try:
                user_sessions = self._list_redis_sync(redis, user_id)
                start = (page - 1) * size
                return user_sessions[start:start + size]
            except Exception as e:
                logger.warning(f"Redis list sessions failed, falling back to memory: {e}")

        user_sessions = [
            session for session in self._sessions.values()
            if session.user_id == user_id and session.status == SessionStatus.ACTIVE
        ]
        user_sessions.sort(key=lambda s: s.last_active_at, reverse=True)
        start = (page - 1) * size
        end = start + size
        return user_sessions[start:end]

    def _list_redis_sync(self, redis: _RedisSessionBackend, user_id: str) -> List[SessionState]:
        r = redis._get_redis()
        members = r.smembers(f"{_RedisSessionBackend._USER_INDEX_PREFIX}{user_id}")
        sessions = []
        for sid in members:
            s = redis._load(sid)
            if s and s.status == SessionStatus.ACTIVE:
                sessions.append(s)
        sessions.sort(key=lambda s: s.last_active_at, reverse=True)
        return sessions

    def count_sessions(self, user_id: str) -> int:
        redis = self._get_redis()
        if redis:
            try:
                return redis._count_user_sessions(user_id)
            except Exception as e:
                logger.warning(f"Redis count sessions failed: {e}")
        return sum(
            1 for s in self._sessions.values()
            if s.user_id == user_id and s.status == SessionStatus.ACTIVE
        )

    def get_conversation_context(self, session_id: str) -> Optional[Dict[str, Any]]:
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
