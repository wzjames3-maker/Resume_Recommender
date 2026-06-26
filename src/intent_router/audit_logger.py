"""
智能招聘 RAG 推荐系统 - Intent 审计日志模块

记录每次意图识别的完整链路
"""

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.common.logger import get_logger

logger = get_logger("intent_audit")


class IntentAuditLog(BaseModel):
    """意图审计日志"""

    log_id: str = Field(..., description="日志唯一标识")
    timestamp: datetime = Field(default_factory=datetime.now(timezone.utc), description="日志时间")
    conversation_id: Optional[str] = Field(None, description="会话 ID")
    user_id: Optional[str] = Field(None, description="用户 ID")

    # 输入信息
    query: str = Field(..., description="用户输入（脱敏后）")
    query_hash: str = Field(..., description="用户输入哈希（用于去重统计）")

    # 意图识别结果
    detected_intent: str = Field(..., description="识别的意图")
    confidence: float = Field(..., description="置信度")
    slots: Dict[str, Any] = Field(default_factory=dict, description="提取的 Slots")

    # 处理信息
    handler: str = Field(..., description="处理器名称")
    response_type: str = Field(..., description="响应类型")
    latency_ms: int = Field(0, description="处理耗时（毫秒）")

    # Fallback 信息
    fallback_triggered: bool = Field(False, description="是否触发 Fallback")
    fallback_reason: Optional[str] = Field(None, description="Fallback 原因")

    # 元信息
    llm_model: Optional[str] = Field(None, description="使用的 LLM 模型")
    llm_tokens_used: Optional[int] = Field(None, description="LLM Token 用量")


class IntentAuditLogger:
    """意图审计日志记录器"""

    def __init__(self):
        """初始化审计日志记录器"""
        self._logs: List[IntentAuditLog] = []
        self._pii_patterns = [
            (re.compile(r"1[3-9]\d{9}"), "手机号"),  # 手机号
            (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "邮箱"),  # 邮箱
            (re.compile(r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"), "身份证"),  # 身份证
        ]

    def log(
        self,
        query: str,
        detected_intent: str,
        confidence: float,
        slots: Dict[str, Any],
        handler: str,
        response_type: str,
        latency_ms: int,
        fallback_triggered: bool = False,
        fallback_reason: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_tokens_used: Optional[int] = None,
    ) -> IntentAuditLog:
        """
        记录审计日志

        Args:
            query: 用户输入
            detected_intent: 识别的意图
            confidence: 置信度
            slots: 提取的 Slots
            handler: 处理器名称
            response_type: 响应类型
            latency_ms: 处理耗时
            fallback_triggered: 是否触发 Fallback
            fallback_reason: Fallback 原因
            conversation_id: 会话 ID
            user_id: 用户 ID
            llm_model: LLM 模型
            llm_tokens_used: LLM Token 用量

        Returns:
            IntentAuditLog: 审计日志
        """
        # 脱敏处理
        desensitized_query = self._desensitize_query(query)

        # 生成查询哈希
        query_hash = self._generate_hash(query)

        # 生成日志 ID
        log_id = self._generate_log_id()

        # 创建日志
        audit_log = IntentAuditLog(
            log_id=log_id,
            conversation_id=conversation_id,
            user_id=user_id,
            query=desensitized_query,
            query_hash=query_hash,
            detected_intent=detected_intent,
            confidence=confidence,
            slots=slots,
            handler=handler,
            response_type=response_type,
            latency_ms=latency_ms,
            fallback_triggered=fallback_triggered,
            fallback_reason=fallback_reason,
            llm_model=llm_model,
            llm_tokens_used=llm_tokens_used,
        )

        # 存储日志
        self._logs.append(audit_log)

        logger.info(
            f"审计日志: intent={detected_intent}, confidence={confidence:.2f}, "
            f"fallback={fallback_triggered}, latency={latency_ms}ms"
        )

        return audit_log

    def _desensitize_query(self, query: str) -> str:
        """
        对查询进行脱敏

        Args:
            query: 原始查询

        Returns:
            str: 脱敏后的查询
        """
        result = query

        # 替换 PII
        for pattern, pii_type in self._pii_patterns:
            result = pattern.sub(f"[{pii_type}]", result)

        return result

    def _generate_hash(self, text: str) -> str:
        """
        生成文本哈希

        Args:
            text: 文本

        Returns:
            str: 哈希值
        """
        import hashlib
        return hashlib.md5(text.encode()).hexdigest()

    def _generate_log_id(self) -> str:
        """
        生成日志 ID

        Returns:
            str: 日志 ID
        """
        import uuid
        return str(uuid.uuid4())

    def get_logs(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        intent: Optional[str] = None,
        fallback_only: bool = False,
        limit: int = 100,
    ) -> List[IntentAuditLog]:
        """
        查询审计日志

        Args:
            start_time: 开始时间
            end_time: 结束时间
            intent: 意图类型
            fallback_only: 只返回 Fallback 日志
            limit: 返回数量限制

        Returns:
            List[IntentAuditLog]: 审计日志列表
        """
        filtered_logs = self._logs

        # 时间过滤
        if start_time:
            filtered_logs = [log for log in filtered_logs if log.timestamp >= start_time]

        if end_time:
            filtered_logs = [log for log in filtered_logs if log.timestamp <= end_time]

        # 意图过滤
        if intent:
            filtered_logs = [log for log in filtered_logs if log.detected_intent == intent]

        # Fallback 过滤
        if fallback_only:
            filtered_logs = [log for log in filtered_logs if log.fallback_triggered]

        # 限制数量
        return filtered_logs[-limit:]

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            Dict: 统计信息
        """
        if not self._logs:
            return {
                "total": 0,
                "fallback_count": 0,
                "fallback_rate": 0.0,
                "avg_latency_ms": 0,
                "intent_distribution": {},
            }

        total = len(self._logs)
        fallback_count = sum(1 for log in self._logs if log.fallback_triggered)
        avg_latency = sum(log.latency_ms for log in self._logs) / total

        # 意图分布
        intent_distribution = {}
        for log in self._logs:
            intent = log.detected_intent
            intent_distribution[intent] = intent_distribution.get(intent, 0) + 1

        return {
            "total": total,
            "fallback_count": fallback_count,
            "fallback_rate": fallback_count / total if total > 0 else 0.0,
            "avg_latency_ms": int(avg_latency),
            "intent_distribution": intent_distribution,
        }

    def clear_logs(self) -> None:
        """清除日志"""
        self._logs.clear()
        logger.info("审计日志已清除")


# 全局审计日志记录器实例
intent_audit_logger = IntentAuditLogger()


def get_intent_audit_logger() -> IntentAuditLogger:
    """获取审计日志记录器实例"""
    return intent_audit_logger
