"""
智能招聘 RAG 推荐系统 - 查询构建器测试
"""

import pytest

from src.common.errors import ValidationError
from src.intent_router.schemas import CandidateSlot
from src.recommendation_engine.query_builder import QueryBuilder, get_query_builder


@pytest.fixture
def builder():
    """创建查询构建器实例"""
    return QueryBuilder()


class TestQueryBuilder:
    """QueryBuilder 测试"""

    def test_build_query_text_with_job_title(self, builder):
        """测试带职位的查询"""
        slots = CandidateSlot(job_title="Java工程师")
        query = builder.build_query_text(slots)

        assert "Java工程师" in query

    def test_build_query_text_with_skills(self, builder):
        """测试带技能的查询"""
        slots = CandidateSlot(skills=["Python", "Django"])
        query = builder.build_query_text(slots)

        assert "Python" in query
        assert "Django" in query

    def test_build_query_text_with_experience(self, builder):
        """测试带工作年限的查询"""
        slots = CandidateSlot(experience=3)
        query = builder.build_query_text(slots)

        assert "3年经验" in query

    def test_build_query_text_with_city(self, builder):
        """测试带城市的查询"""
        slots = CandidateSlot(city="北京")
        query = builder.build_query_text(slots)

        assert "北京" in query

    def test_build_query_text_full(self, builder):
        """测试完整查询"""
        slots = CandidateSlot(
            job_title="Java工程师",
            skills=["Spring Boot"],
            experience=3,
            city="北京",
        )
        query = builder.build_query_text(slots)

        assert "Java工程师" in query
        assert "Spring Boot" in query
        assert "3年经验" in query
        assert "北京" in query

    def test_build_query_text_empty_slots(self, builder):
        """测试空 Slots"""
        slots = CandidateSlot()

        with pytest.raises(ValidationError) as exc_info:
            builder.build_query_text(slots)

        assert "查询条件为空" in str(exc_info.value)

    def test_build_query_text_remove_stop_words(self, builder):
        """测试去停用词"""
        slots = CandidateSlot(job_title="的Java工程师")
        query = builder.build_query_text(slots)

        # 停用词应该被移除
        assert "的" not in query.split()

    def test_extract_keywords(self, builder):
        """测试提取关键词"""
        slots = CandidateSlot(
            job_title="Java工程师",
            skills=["Python", "Django"],
            experience=3,
            city="北京",
        )

        keywords = builder._extract_keywords(slots)

        assert "Java工程师" in keywords
        assert "Python" in keywords
        assert "Django" in keywords
        assert "3年经验" in keywords
        assert "北京" in keywords

    def test_remove_stop_words(self, builder):
        """测试去停用词"""
        text = "的 Java 工程师 在 北京"
        result = builder._remove_stop_words(text)

        assert "的" not in result
        assert "在" not in result
        assert "Java" in result
        assert "工程师" in result

    def test_build_empty_query_error(self, builder):
        """测试构建空查询错误"""
        error = builder.build_empty_query_error()

        assert isinstance(error, ValidationError)
        assert "查询条件为空" in str(error)

    def test_get_query_builder(self):
        """测试获取全局实例"""
        builder = get_query_builder()
        assert isinstance(builder, QueryBuilder)
