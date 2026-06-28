"""
智能招聘 RAG 推荐系统 - Intent 分类器测试
"""

import pytest

from src.intent_router.classifier import IntentClassifier, get_intent_classifier
from src.intent_router.schemas import (
    CandidateSlot,
    ConversationContext,
    IntentEnum,
    IntentResult,
    QuerySlot,
)


@pytest.fixture
def classifier():
    """创建意图分类器实例"""
    return IntentClassifier()


class TestIntentEnum:
    """IntentEnum 测试"""

    def test_intent_values(self):
        """测试意图枚举值"""
        assert IntentEnum.RECRUITMENT_SEARCH.value == "recruitment.search"
        assert IntentEnum.RECRUITMENT_REFINE.value == "recruitment.refine"
        assert IntentEnum.CANDIDATE_LOOKUP.value == "candidate.lookup"
        assert IntentEnum.CHAT.value == "chat"
        assert IntentEnum.FALLBACK.value == "fallback"


class TestCandidateSlot:
    """CandidateSlot 测试"""

    def test_create_empty_slot(self):
        """测试创建空 Slot"""
        slot = CandidateSlot()
        assert slot.job_title is None
        assert slot.skills is None
        assert slot.experience is None

    def test_create_slot_with_values(self):
        """测试创建带值的 Slot"""
        slot = CandidateSlot(
            job_title="Java工程师",
            skills=["Java", "Spring Boot"],
            experience=5,
            city="北京",
        )

        assert slot.job_title == "Java工程师"
        assert slot.skills == ["Java", "Spring Boot"]
        assert slot.experience == 5
        assert slot.city == "北京"


class TestQuerySlot:
    """QuerySlot 测试"""

    def test_default_values(self):
        """测试默认值"""
        slot = QuerySlot()
        assert slot.count == 10
        assert slot.sort_by == "score"
        assert slot.order == "desc"
        assert slot.page == 1
        assert slot.top_k == 50


class TestIntentResult:
    """IntentResult 测试"""

    def test_create_result(self):
        """测试创建结果"""
        result = IntentResult(
            intent=IntentEnum.RECRUITMENT_SEARCH,
            confidence=0.9,
            raw_query="帮我找Java工程师",
            reasoning="用户明确表达招聘需求",
        )

        assert result.intent == IntentEnum.RECRUITMENT_SEARCH
        assert result.confidence == 0.9
        assert result.raw_query == "帮我找Java工程师"
        assert isinstance(result.candidate_slots, CandidateSlot)
        assert isinstance(result.query_slots, QuerySlot)


class TestConversationContext:
    """ConversationContext 测试"""

    def test_create_context(self):
        """测试创建上下文"""
        context = ConversationContext(
            conversation_id="conv-001",
            turn_count=3,
            last_intent=IntentEnum.RECRUITMENT_SEARCH,
        )

        assert context.conversation_id == "conv-001"
        assert context.turn_count == 3
        assert context.last_intent == IntentEnum.RECRUITMENT_SEARCH
        assert context.intent_history == []


class TestIntentClassifier:
    """IntentClassifier 测试"""

    def test_get_cache_key(self, classifier):
        """测试生成缓存键"""
        key1 = classifier._cache_key("测试文本", None)
        key2 = classifier._cache_key("测试文本", None)
        key3 = classifier._cache_key("其他文本", None)

        assert key1 == key2  # 相同输入应该有相同的键
        assert key1 != key3  # 不同输入应该有不同的键

    def test_get_cache_key_with_context(self, classifier):
        """测试带上下文的缓存键"""
        context = ConversationContext(
            conversation_id="conv-001",
            turn_count=1,
        )

        key1 = classifier._cache_key("测试文本", context)
        key2 = classifier._cache_key("测试文本", None)

        assert key1 != key2  # 有无上下文应该有不同的键

    def test_cache_operations(self, classifier):
        """测试缓存操作"""
        result = IntentResult(
            intent=IntentEnum.CHAT,
            confidence=0.8,
            raw_query="测试",
        )

        # 存入缓存
        classifier._to_cache("test_key", result)

        # 从缓存获取
        cached = classifier._from_cache("test_key")
        assert cached is not None
        assert cached.intent == IntentEnum.CHAT

        # 不存在的键
        assert classifier._from_cache("nonexistent") is None

        # 清除缓存
        classifier.clear_cache()
        assert classifier._from_cache("test_key") is None

    def test_keyword_fallback_search(self, classifier):
        """测试关键词降级 - 搜索"""
        result = classifier._keyword_fallback("帮我找Java工程师")

        assert result.intent == IntentEnum.RECRUITMENT_SEARCH
        assert result.confidence == 0.6
        assert "找" in result.reasoning

    def test_keyword_fallback_refine(self, classifier):
        """测试关键词降级 - 修正"""
        result = classifier._keyword_fallback("把这些结果按薪资排序")

        assert result.intent == IntentEnum.RECRUITMENT_REFINE
        assert result.confidence == 0.6

    def test_keyword_fallback_lookup(self, classifier):
        """测试关键词降级 - 查看"""
        result = classifier._keyword_fallback("张三的简历详情")

        assert result.intent == IntentEnum.CANDIDATE_LOOKUP
        assert result.confidence == 0.6

    def test_keyword_fallback_chat(self, classifier):
        """测试关键词降级 - 闲聊"""
        result = classifier._keyword_fallback("你好")

        assert result.intent == IntentEnum.CHAT
        assert result.confidence == 0.6

    def test_keyword_fallback_unknown(self, classifier):
        """测试关键词降级 - 未知"""
        result = classifier._keyword_fallback("一些无法识别的输入 xyz")

        assert result.intent == IntentEnum.CHAT
        assert result.confidence == 0.5

    def test_set_confidence_threshold(self, classifier):
        """测试设置置信度阈值"""
        classifier.set_confidence_threshold(0.8)
        assert classifier.confidence_threshold == 0.8

        # 测试边界值
        classifier.set_confidence_threshold(1.5)
        assert classifier.confidence_threshold == 1.0

        classifier.set_confidence_threshold(-0.5)
        assert classifier.confidence_threshold == 0.0

    def test_get_intent_classifier(self):
        """测试获取全局实例"""
        classifier = get_intent_classifier()
        assert isinstance(classifier, IntentClassifier)


class TestIntentClassifierIntegration:
    """IntentClassifier 集成测试（需要 LLM API）"""

    @pytest.mark.skip(reason="需要 LLM API 调用")
    def test_classify_search(self, classifier):
        """测试识别搜索意图（需要 API）"""
        result = classifier.classify("帮我找3年经验的Java开发")

        assert result.intent == IntentEnum.RECRUITMENT_SEARCH
        assert result.confidence >= 0.8

    @pytest.mark.skip(reason="需要 LLM API 调用")
    def test_classify_refine(self, classifier):
        """测试识别修正意图（需要 API）"""
        result = classifier.classify("把这些结果按薪资排序")

        assert result.intent == IntentEnum.RECRUITMENT_REFINE

    @pytest.mark.skip(reason="需要 LLM API 调用")
    def test_classify_with_context(self, classifier):
        """测试带上下文的意图识别（需要 API）"""
        context = ConversationContext(
            conversation_id="conv-001",
            turn_count=2,
            last_intent=IntentEnum.RECRUITMENT_SEARCH,
        )

        result = classifier.classify("再推荐几个", context)

        assert result.intent == IntentEnum.RECRUITMENT_REFINE
