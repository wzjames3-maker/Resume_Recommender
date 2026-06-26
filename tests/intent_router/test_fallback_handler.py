"""
智能招聘 RAG 推荐系统 - Intent Fallback 测试
"""

import pytest

from src.intent_router.fallback_handler import (
    FallbackResponse,
    IntentFallbackHandler,
    get_intent_fallback_handler,
)
from src.intent_router.schemas import (
    CandidateSlot,
    IntentEnum,
    IntentResult,
    QuerySlot,
)


@pytest.fixture
def handler():
    """创建 Fallback 处理器实例"""
    return IntentFallbackHandler()


@pytest.fixture
def high_confidence_result():
    """高置信度结果"""
    return IntentResult(
        intent=IntentEnum.RECRUITMENT_SEARCH,
        confidence=0.9,
        candidate_slots=CandidateSlot(job_title="Java工程师"),
        query_slots=QuerySlot(),
        raw_query="帮我找Java工程师",
    )


@pytest.fixture
def medium_confidence_result():
    """中等置信度结果"""
    return IntentResult(
        intent=IntentEnum.RECRUITMENT_SEARCH,
        confidence=0.6,
        candidate_slots=CandidateSlot(),
        query_slots=QuerySlot(),
        raw_query="找人",
    )


@pytest.fixture
def low_confidence_result():
    """低置信度结果"""
    return IntentResult(
        intent=IntentEnum.CHAT,
        confidence=0.3,
        candidate_slots=CandidateSlot(),
        query_slots=QuerySlot(),
        raw_query="一些无法理解的输入",
    )


class TestFallbackResponse:
    """FallbackResponse 测试"""

    def test_create_response(self):
        """测试创建响应"""
        response = FallbackResponse(
            message="测试消息",
            suggested_intents=[IntentEnum.RECRUITMENT_SEARCH],
            fallback_reason="测试原因",
        )

        assert response.message == "测试消息"
        assert IntentEnum.RECRUITMENT_SEARCH in response.suggested_intents
        assert response.fallback_reason == "测试原因"
        assert response.is_fallback is True


class TestIntentFallbackHandler:
    """IntentFallbackHandler 测试"""

    def test_handle_high_confidence(self, handler, high_confidence_result):
        """测试高置信度处理"""
        response = handler.handle(high_confidence_result)

        assert response.is_fallback is False
        assert response.message == ""

    def test_handle_medium_confidence_search(self, handler, medium_confidence_result):
        """测试中等置信度处理（搜索）"""
        response = handler.handle(medium_confidence_result)

        assert response.is_fallback is True
        assert "搜索候选人" in response.message
        assert len(response.suggested_intents) > 0
        assert "置信度不足" in response.fallback_reason

    def test_handle_low_confidence(self, handler, low_confidence_result):
        """测试低置信度处理"""
        response = handler.handle(low_confidence_result)

        assert response.is_fallback is True
        assert "抱歉" in response.message
        assert "置信度过低" in response.fallback_reason

    def test_handle_llm_error(self, handler, high_confidence_result):
        """测试 LLM 错误处理"""
        error = Exception("LLM 调用超时")
        response = handler.handle(high_confidence_result, error=error)

        assert response.is_fallback is True
        assert "系统暂时无法理解" in response.message
        assert "LLM 调用失败" in response.fallback_reason

    def test_handle_no_context_refine(self, handler):
        """测试无上下文 refine 处理"""
        response = handler.handle_no_context_refine()

        assert response.is_fallback is True
        assert "请先描述" in response.message
        assert "无上下文" in response.fallback_reason

    def test_get_suggested_intents_search(self, handler):
        """测试获取搜索建议"""
        suggestions = handler._get_suggested_intents(IntentEnum.RECRUITMENT_SEARCH)

        assert IntentEnum.RECRUITMENT_SEARCH in suggestions
        assert IntentEnum.RECRUITMENT_REFINE in suggestions
        assert IntentEnum.CANDIDATE_LOOKUP in suggestions

    def test_get_suggested_intents_lookup(self, handler):
        """测试获取查看建议"""
        suggestions = handler._get_suggested_intents(IntentEnum.CANDIDATE_LOOKUP)

        assert IntentEnum.CANDIDATE_LOOKUP in suggestions
        assert IntentEnum.RECRUITMENT_SEARCH in suggestions

    def test_threshold_configuration(self):
        """测试阈值配置"""
        handler = IntentFallbackHandler(high_threshold=0.8, low_threshold=0.5)

        assert handler.high_threshold == 0.8
        assert handler.low_threshold == 0.5

    def test_get_intent_fallback_handler(self):
        """测试获取全局实例"""
        handler = get_intent_fallback_handler()
        assert isinstance(handler, IntentFallbackHandler)
