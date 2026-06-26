"""
智能招聘 RAG 推荐系统 - 端到端测试

recruitment.search 端到端测试
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock

from src.intent_router.schemas import (
    CandidateSlot,
    IntentEnum,
    IntentResult,
    QuerySlot,
)
from src.conversation_memory.workflow import RecruitmentWorkflow, WorkflowResult


class TestRecruitmentSearchE2E:
    """recruitment.search 端到端测试"""

    @pytest.fixture
    def workflow(self):
        return RecruitmentWorkflow()

    @pytest.fixture
    def search_intent_result(self):
        return IntentResult(
            intent=IntentEnum.RECRUITMENT_SEARCH,
            confidence=0.9,
            candidate_slots=CandidateSlot(
                job_title="Java工程师",
                skills=["Java", "Spring Boot"],
                experience=3,
                city="北京",
            ),
            query_slots=QuerySlot(count=10),
            raw_query="帮我找3年Java经验在北京的候选人",
        )

    def test_search_workflow_structure(self, workflow, search_intent_result):
        """测试搜索工作流结构"""
        # 验证工作流组件存在
        assert workflow.session_manager is not None
        assert workflow.slot_merger is not None
        assert workflow.scope_decider is not None
        assert workflow.hybrid_retriever is not None
        assert workflow.metadata_filter is not None
        assert workflow.reranker is not None
        assert workflow.reason_generator is not None
        assert workflow.degradation_strategy is not None

    def test_workflow_result_structure(self):
        """测试工作流结果结构"""
        result = WorkflowResult(
            success=True,
            message="找到5位候选人",
            candidates=[
                {
                    "resume_id": "R001",
                    "chunk_id": "R001:small:0",
                    "content": "候选人内容",
                    "score": 0.9,
                    "rank": 1,
                    "reason": {
                        "reason": "推荐理由",
                        "matched_skills": ["Java"],
                        "missing_skills": [],
                        "score_breakdown": {},
                    },
                }
            ],
            session_id="session-001",
        )

        assert result.success is True
        assert len(result.candidates) == 1
        assert result.session_id == "session-001"

        # 测试转换为字典
        data = result.to_dict()
        assert "success" in data
        assert "candidates" in data
        assert "session_id" in data


class TestSearchComponentsIntegration:
    """搜索组件集成测试"""

    def test_slot_merger_with_search_slots(self):
        """测试 Slot 合并与搜索 Slots"""
        from src.conversation_memory.slot_merger import SlotMerger, MergeStrategy

        merger = SlotMerger()

        old_slots = CandidateSlot(job_title="Python工程师")
        new_slots = CandidateSlot(
            job_title="Java工程师",
            experience=3,
            city="北京",
        )

        merged = merger.merge_candidate_slots(new_slots, old_slots, MergeStrategy.INCREMENTAL)

        assert merged.job_title == "Java工程师"
        assert merged.experience == 3
        assert merged.city == "北京"

    def test_scope_decider_with_search_intent(self):
        """测试范围决策器与搜索意图"""
        from src.conversation_memory.scope_decider import ScopeDecider, SearchScope

        decider = ScopeDecider()

        slots = CandidateSlot(job_title="Java工程师")

        decision = decider.decide(
            IntentEnum.RECRUITMENT_SEARCH,
            slots,
        )

        assert decision.scope == SearchScope.FULL
        assert "新搜索" in decision.reason

    def test_scope_decider_with_refine_intent(self):
        """测试范围决策器与修正意图"""
        from src.conversation_memory.scope_decider import ScopeDecider, SearchScope

        decider = ScopeDecider()

        new_slots = CandidateSlot(sort_by="experience")
        old_slots = CandidateSlot(job_title="Java工程师")
        last_candidates = [{"resume_id": "R001"}, {"resume_id": "R002"}]

        decision = decider.decide(
            IntentEnum.RECRUITMENT_REFINE,
            new_slots,
            old_slots,
            last_candidates,
        )

        # 只是排序变化，应该在上次结果中检索
        assert decision.scope == SearchScope.NARROW
        assert len(decision.candidate_ids) == 2

    def test_reason_generator_integration(self):
        """测试推荐理由生成器集成"""
        from src.recommendation_engine.reason_generator import ReasonGenerator
        from src.recommendation_engine.hybrid_retriever import RetrievalResult

        generator = ReasonGenerator()

        result = RetrievalResult(
            resume_id="R001",
            chunk_id="R001:small:0",
            chunk_level="small",
            parent_chunk_id="R001:parent:0",
            content="候选人内容",
            score=0.9,
            rank=1,
            metadata={
                "candidate_name": "张三",
                "skills": ["Java", "Spring Boot", "MySQL"],
                "years_of_experience": 3,
                "final_score": 0.85,
            },
        )

        slots = CandidateSlot(
            skills=["Java", "Spring Boot"],
        )

        reason = generator.generate(result, slots)

        assert "张三" in reason.reason
        assert "Java" in reason.matched_skills
        assert "Spring Boot" in reason.matched_skills
        assert len(reason.missing_skills) == 0
        assert "semantic_score" in reason.score_breakdown
