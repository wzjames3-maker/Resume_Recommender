"""
智能招聘 RAG 推荐系统 - Slot 提取器测试
"""

import pytest

from src.intent_router.schemas import (
    CandidateSlot,
    ConversationContext,
    IntentEnum,
    IntentResult,
    QuerySlot,
)
from src.intent_router.slot_extractor import SlotExtractor, get_slot_extractor


@pytest.fixture
def extractor():
    """创建 Slot 提取器实例"""
    return SlotExtractor()


@pytest.fixture
def sample_intent_result():
    """示例意图识别结果"""
    return IntentResult(
        intent=IntentEnum.RECRUITMENT_SEARCH,
        confidence=0.9,
        candidate_slots=CandidateSlot(
            job_title="Java工程师",
            experience=3,
            city="北京",
        ),
        query_slots=QuerySlot(count=10),
        raw_query="找3年Java经验在北京的候选人",
    )


class TestSlotExtractor:
    """SlotExtractor 测试"""

    def test_extract_and_merge_no_context(self, extractor, sample_intent_result):
        """测试无上下文时的提取"""
        result = extractor.extract_and_merge(sample_intent_result, None)

        assert result.intent == IntentEnum.RECRUITMENT_SEARCH
        assert result.candidate_slots.job_title == "Java工程师"
        assert result.candidate_slots.experience == 3
        assert result.candidate_slots.city == "北京"

    def test_extract_and_merge_with_context(self, extractor, sample_intent_result):
        """测试有上下文时的合并"""
        context = ConversationContext(
            conversation_id="conv-001",
            turn_count=2,
            last_query={
                "candidate_slots": {
                    "job_title": "Python工程师",
                    "skills": ["Python", "Django"],
                },
                "query_slots": {"count": 20},
            },
        )

        result = extractor.extract_and_merge(sample_intent_result, context)

        # 新值应该覆盖旧值
        assert result.candidate_slots.job_title == "Java工程师"
        # 旧值应该保留
        assert result.candidate_slots.skills == ["Python", "Django"]
        # 新值应该覆盖
        assert result.candidate_slots.experience == 3

    def test_merge_candidate_slots_new_value_overrides(self, extractor):
        """测试新值覆盖旧值"""
        new_slots = CandidateSlot(job_title="Java工程师", experience=5)
        old_slots_data = {"job_title": "Python工程师", "city": "上海"}

        merged = extractor._merge_candidate_slots(new_slots, old_slots_data)

        assert merged.job_title == "Java工程师"  # 新值覆盖
        assert merged.experience == 5  # 新值
        assert merged.city == "上海"  # 旧值保留

    def test_merge_candidate_slots_none_keeps_old(self, extractor):
        """测试 None 保留旧值"""
        new_slots = CandidateSlot(job_title="Java工程师")
        old_slots_data = {"job_title": "Python工程师", "experience": 3}

        merged = extractor._merge_candidate_slots(new_slots, old_slots_data)

        assert merged.job_title == "Java工程师"  # 新值覆盖
        assert merged.experience == 3  # 旧值保留（新值为 None）

    def test_merge_query_slots(self, extractor):
        """测试合并 QuerySlot"""
        new_slots = QuerySlot(count=20, sort_by="experience")
        old_slots_data = {"count": 10, "order": "asc"}

        merged = extractor._merge_query_slots(new_slots, old_slots_data)

        assert merged.count == 20  # 新值覆盖
        assert merged.sort_by == "experience"  # 新值
        assert merged.order == "asc"  # 旧值保留

    def test_validate_slots_search_missing(self, extractor):
        """测试验证搜索意图缺少条件"""
        intent_result = IntentResult(
            intent=IntentEnum.RECRUITMENT_SEARCH,
            confidence=0.9,
            candidate_slots=CandidateSlot(),  # 空 Slots
            query_slots=QuerySlot(),
            raw_query="帮我找人",
        )

        warnings = extractor.validate_slots(intent_result)

        assert len(warnings) > 0
        assert "缺少候选人条件" in warnings[0]

    def test_validate_slots_search_complete(self, extractor, sample_intent_result):
        """测试验证搜索意图完整"""
        warnings = extractor.validate_slots(sample_intent_result)

        assert len(warnings) == 0

    def test_validate_slots_lookup_missing(self, extractor):
        """测试验证查看意图缺少标识"""
        intent_result = IntentResult(
            intent=IntentEnum.CANDIDATE_LOOKUP,
            confidence=0.9,
            candidate_slots=CandidateSlot(),  # 空 Slots
            query_slots=QuerySlot(),
            raw_query="查看简历",
        )

        warnings = extractor.validate_slots(intent_result)

        assert len(warnings) > 0
        assert "缺少候选人标识" in warnings[0]

    def test_get_slot_extractor(self):
        """测试获取全局实例"""
        extractor = get_slot_extractor()
        assert isinstance(extractor, SlotExtractor)
