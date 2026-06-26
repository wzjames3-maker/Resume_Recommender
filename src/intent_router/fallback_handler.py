"""
智能招聘 RAG 推荐系统 - Intent Fallback 处理模块

处理意图识别失败或置信度低的情况
"""

from typing import List, Optional

from src.common.logger import get_logger
from src.intent_router.schemas import (
    CandidateSlot,
    IntentEnum,
    IntentResult,
    QuerySlot,
)

logger = get_logger("intent_fallback")

# 默认阈值
CONFIDENCE_HIGH_THRESHOLD = 0.7
CONFIDENCE_LOW_THRESHOLD = 0.4


class FallbackResponse:
    """Fallback 响应"""

    def __init__(
        self,
        message: str,
        suggested_intents: Optional[List[IntentEnum]] = None,
        fallback_reason: str = "",
        is_fallback: bool = True,
    ):
        self.message = message
        self.suggested_intents = suggested_intents or []
        self.fallback_reason = fallback_reason
        self.is_fallback = is_fallback


class IntentFallbackHandler:
    """Intent Fallback 处理器"""

    def __init__(
        self,
        high_threshold: float = CONFIDENCE_HIGH_THRESHOLD,
        low_threshold: float = CONFIDENCE_LOW_THRESHOLD,
    ):
        """
        初始化 Fallback 处理器

        Args:
            high_threshold: 高置信度阈值
            low_threshold: 低置信度阈值
        """
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold

    def handle(
        self,
        intent_result: IntentResult,
        error: Optional[Exception] = None,
    ) -> FallbackResponse:
        """
        处理 Fallback

        Args:
            intent_result: 意图识别结果
            error: 异常信息（可选）

        Returns:
            FallbackResponse: Fallback 响应
        """
        confidence = intent_result.confidence

        # 检查是否需要 Fallback
        if error:
            return self._handle_llm_error(error)

        if confidence >= self.high_threshold:
            # 高置信度，不需要 Fallback
            return FallbackResponse(
                message="",
                is_fallback=False,
            )

        if confidence >= self.low_threshold:
            # 中等置信度，返回引导性回复
            return self._handle_medium_confidence(intent_result)

        # 低置信度，返回通用兜底回复
        return self._handle_low_confidence(intent_result)

    def _handle_llm_error(self, error: Exception) -> FallbackResponse:
        """
        处理 LLM 调用错误

        Args:
            error: 异常信息

        Returns:
            FallbackResponse: Fallback 响应
        """
        logger.warning(f"LLM 调用失败: {str(error)}")

        return FallbackResponse(
            message="抱歉，系统暂时无法理解您的需求。您可以尝试：\n1. 重新描述您的招聘需求\n2. 使用更简洁的表达\n3. 稍后再试",
            fallback_reason=f"LLM 调用失败: {str(error)}",
        )

    def _handle_medium_confidence(self, intent_result: IntentResult) -> FallbackResponse:
        """
        处理中等置信度

        Args:
            intent_result: 意图识别结果

        Returns:
            FallbackResponse: Fallback 响应
        """
        # 根据识别的意图提供引导
        suggested_intents = self._get_suggested_intents(intent_result.intent)

        # 构建引导性回复
        if intent_result.intent == IntentEnum.RECRUITMENT_SEARCH:
            message = "您是想搜索候选人吗？请提供更多信息，例如：\n- 目标职位（如 Java 工程师）\n- 工作年限（如 3 年以上）\n- 技能要求（如 Spring Boot）\n- 工作城市（如 北京）"
        elif intent_result.intent == IntentEnum.CANDIDATE_LOOKUP:
            message = "您是想查看候选人详情吗？请提供候选人姓名或 ID。"
        elif intent_result.intent == IntentEnum.RECRUITMENT_REFINE:
            message = "您是想修改搜索条件吗？请描述您想调整的内容。"
        else:
            message = '我不太确定您的意思。您可以：\n1. 描述您的招聘需求（如"帮我找Java工程师"）\n2. 查看候选人详情（如"张三的简历"）\n3. 修改搜索条件（如"按薪资排序"）'

        return FallbackResponse(
            message=message,
            suggested_intents=suggested_intents,
            fallback_reason=f"置信度不足: {intent_result.confidence:.2f}",
        )

    def _handle_low_confidence(self, intent_result: IntentResult) -> FallbackResponse:
        """
        处理低置信度

        Args:
            intent_result: 意图识别结果

        Returns:
            FallbackResponse: Fallback 响应
        """
        return FallbackResponse(
            message='抱歉，我无法理解您的需求。请尝试：\n1. 描述您的招聘需求（如"帮我找Java工程师"）\n2. 查看候选人详情（如"张三的简历"）\n3. 输入"帮助"查看更多用法',
            fallback_reason=f"置信度过低: {intent_result.confidence:.2f}",
        )

    def _get_suggested_intents(self, intent: IntentEnum) -> List[IntentEnum]:
        """
        获取建议的意图列表

        Args:
            intent: 当前识别的意图

        Returns:
            List[IntentEnum]: 建议的意图列表
        """
        # 根据当前意图提供相关建议
        suggestions = {
            IntentEnum.RECRUITMENT_SEARCH: [
                IntentEnum.RECRUITMENT_SEARCH,
                IntentEnum.RECRUITMENT_REFINE,
                IntentEnum.CANDIDATE_LOOKUP,
            ],
            IntentEnum.RECRUITMENT_REFINE: [
                IntentEnum.RECRUITMENT_REFINE,
                IntentEnum.RECRUITMENT_SEARCH,
            ],
            IntentEnum.CANDIDATE_LOOKUP: [
                IntentEnum.CANDIDATE_LOOKUP,
                IntentEnum.RECRUITMENT_SEARCH,
            ],
        }

        return suggestions.get(intent, [
            IntentEnum.RECRUITMENT_SEARCH,
            IntentEnum.CANDIDATE_LOOKUP,
            IntentEnum.CHAT,
        ])

    def handle_no_context_refine(self) -> FallbackResponse:
        """
        处理无上下文的 refine 意图

        Returns:
            FallbackResponse: Fallback 响应
        """
        return FallbackResponse(
            message='请先描述您的招聘需求，例如"帮我找Java工程师"，然后再进行条件调整。',
            fallback_reason="无上下文时收到 refine 意图",
        )


# 全局 Fallback 处理器实例
intent_fallback_handler = IntentFallbackHandler()


def get_intent_fallback_handler() -> IntentFallbackHandler:
    """获取 Fallback 处理器实例"""
    return intent_fallback_handler
