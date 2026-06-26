"""
智能招聘 RAG 推荐系统 - 意图路由分发器

根据意图类型将请求分发到对应的 Handler
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

"""
意图路由分发器

架构说明：
    Handler 基类和 IntentRouter 定义了意图处理的标准接口。
    当前实现中，SearchHandler / RefineHandler / LookupHandler 为桩实现，
    实际业务逻辑在 conversation_memory/workflow.py 中。
    chat.py 直接通过 if/elif 分支调用 workflow.py 的方法。

    如需统一路由逻辑，应将 chat.py 重构为通过 IntentRouter.dispatch() 分发，
    并将 Handler 实现委托给 workflow.py 的对应方法。
"""
from src.common.logger import get_logger
from src.intent_router.schemas import (
    ConversationContext,
    IntentEnum,
    IntentResult,
)

logger = get_logger("intent_router")


class HandlerResponse:
    """Handler 响应基类"""

    def __init__(
        self,
        success: bool = True,
        message: str = "",
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        self.success = success
        self.message = message
        self.data = data or {}
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "error": self.error,
        }


# Handler classes removed in v1.2-data-pipeline.
# Actual routing is done directly in src/api/v1/chat.py via a mapping table.
# See tasks/iter-m-data-pipeline/PIP-T08-cleanup-intent-router.md for context.

class IntentRouter:
    """意图路由分发器"""

    def __init__(self):
        """初始化路由分发器"""
        self._handlers: Dict[IntentEnum, Any] = {}
        # Handlers removed in v1.2-data-pipeline; routing via chat.py mapping table

    def _register_default_handlers(self) -> None:
        """Handlers removed in v1.2-data-pipeline; routing via chat.py mapping table"""
        pass

    def register(self, intent: IntentEnum, handler: Any) -> None:
        """
        注册处理器

        Args:
            intent: 意图类型
            handler: 处理器实例
        """
        self._handlers[intent] = handler
        logger.info(f"注册处理器: {intent.value} -> {handler.__class__.__name__}")

    def unregister(self, intent: IntentEnum) -> None:
        """
        注销处理器

        Args:
            intent: 意图类型
        """
        if intent in self._handlers:
            del self._handlers[intent]
            logger.info(f"注销处理器: {intent.value}")

    def get_handler(self, intent: IntentEnum) -> Optional[Any]:
        """
        获取处理器

        Args:
            intent: 意图类型

        Returns:
            Optional[Any]: 处理器实例，不存在返回 None
        """
        return self._handlers.get(intent)

    async def route(
        self,
        intent_result: IntentResult,
        context: Optional[ConversationContext] = None,
    ) -> HandlerResponse:
        """
        路由分发

        Args:
            intent_result: 意图识别结果
            context: 对话上下文

        Returns:
            HandlerResponse: 处理结果
        """
        intent = intent_result.intent

        # 获取处理器
        handler = self.get_handler(intent)

        if not handler:
            logger.warning(f"未找到处理器: {intent.value}，使用兜底处理器")
            handler = self._handlers.get(IntentEnum.FALLBACK)

            if not handler:
                return HandlerResponse(
                    success=False,
                    message="系统错误：未找到处理器",
                    error="No handler found",
                )

        # 调用处理器
        try:
            response = await handler.handle(intent_result, context)
            logger.info(f"路由分发成功: {intent.value}")
            return response

        except Exception as e:
            logger.error(f"处理器执行失败: {intent.value}, 错误: {str(e)}")
            return HandlerResponse(
                success=False,
                message="处理请求时发生错误",
                error=str(e),
            )

    def get_registered_intents(self) -> List[IntentEnum]:
        """
        获取已注册的意图列表

        Returns:
            List[IntentEnum]: 已注册的意图列表
        """
        return list(self._handlers.keys())


# 全局路由分发器实例
intent_router = IntentRouter()


def get_intent_router() -> IntentRouter:
    """获取路由分发器实例"""
    return intent_router
