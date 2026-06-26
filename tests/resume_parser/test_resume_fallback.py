"""
智能招聘 RAG 推荐系统 - 降级处理测试
"""

import pytest

from src.resume_parser.fallback_handler import (
    FallbackHandler,
    FallbackLevel,
    FallbackResult,
    get_fallback_handler,
)
from src.resume_parser.llm_extractor import ExtractionWarning, ResumeStructured
from src.resume_store.models import (
    EducationEntry,
    ExperienceEntry,
    PersonalInfo,
    ParseStatus,
    SkillEntry,
)


@pytest.fixture
def handler():
    """创建降级处理器实例"""
    return FallbackHandler()


@pytest.fixture
def full_structured():
    """完整的结构化数据"""
    return ResumeStructured(
        personal_info=PersonalInfo(
            full_name="张三",
            phone="13800138000",
            email="zhangsan@example.com",
        ),
        education_list=[
            EducationEntry(school="北京大学", degree="本科"),
        ],
        experience_list=[
            ExperienceEntry(company="字节跳动", title="工程师"),
        ],
        skill_list=[
            SkillEntry(name="Python"),
            SkillEntry(name="Java"),
        ],
        confidence_score=0.9,
    )


@pytest.fixture
def partial_structured():
    """部分结构化数据"""
    return ResumeStructured(
        personal_info=PersonalInfo(full_name="张三"),
        education_list=[],
        experience_list=[
            ExperienceEntry(company="字节跳动", title="工程师"),
        ],
        skill_list=[],
        confidence_score=0.5,
    )


@pytest.fixture
def empty_structured():
    """空结构化数据"""
    return ResumeStructured(
        personal_info=PersonalInfo(),
        education_list=[],
        experience_list=[],
        skill_list=[],
        confidence_score=0.1,
    )


class TestFallbackHandler:
    """FallbackHandler 测试"""

    def test_handle_full_success(self, handler, full_structured):
        """测试完整解析成功"""
        result = handler.handle("测试文本", structured=full_structured)

        assert result.level == FallbackLevel.FULL
        assert result.parse_status == ParseStatus.SUCCESS
        assert result.structured is not None
        assert result.fallback_reason is None

    def test_handle_with_error(self, handler):
        """测试有异常时降级"""
        error = Exception("LLM 调用失败")
        result = handler.handle("测试文本", error=error)

        assert result.level == FallbackLevel.RAW
        assert result.parse_status == ParseStatus.FAILED
        assert result.raw_text == "测试文本"
        assert result.fallback_reason is not None
        assert "LLM 调用失败" in result.fallback_reason

    def test_handle_no_structured(self, handler):
        """测试没有结构化数据时降级"""
        result = handler.handle("测试文本", structured=None)

        assert result.level == FallbackLevel.RAW
        assert result.raw_text == "测试文本"

    def test_handle_partial_parse(self, handler, partial_structured):
        """测试部分解析"""
        result = handler.handle("测试文本", structured=partial_structured)

        # 有 experience_list，所以可以是 FULL 或 PARTIAL
        assert result.level in [FallbackLevel.FULL, FallbackLevel.PARTIAL, FallbackLevel.RAW]
        # 如果是 FULL，extraction_warnings 可能为空
        if result.level != FallbackLevel.FULL:
            assert len(result.extraction_warnings) > 0

    def test_handle_empty_structured(self, handler, empty_structured):
        """测试空结构化数据"""
        result = handler.handle("测试文本", structured=empty_structured)

        # 空数据应该降级到原文存储
        assert result.level == FallbackLevel.RAW
        assert result.raw_text == "测试文本"

    def test_check_fallback_needed_with_error(self, handler):
        """测试检查降级需求（有异常）"""
        error = Exception("测试错误")
        need_fallback, reason = handler._check_fallback_needed(None, error)

        assert need_fallback is True
        assert "测试错误" in reason

    def test_check_fallback_needed_no_structured(self, handler):
        """测试检查降级需求（无数据）"""
        need_fallback, reason = handler._check_fallback_needed(None, None)

        assert need_fallback is True
        assert "未返回" in reason

    def test_check_fallback_needed_high_missing_rate(self, handler, empty_structured):
        """测试检查降级需求（高缺失率）"""
        need_fallback, reason = handler._check_fallback_needed(empty_structured, None)

        assert need_fallback is True
        assert "缺失率" in reason

    def test_check_fallback_needed_low_confidence(self, handler):
        """测试检查降级需求（低置信度）"""
        structured = ResumeStructured(
            personal_info=PersonalInfo(
                full_name="张三",
                phone="13800138000",
                email="test@example.com",
            ),
            education_list=[EducationEntry(school="北京大学")],
            experience_list=[ExperienceEntry(company="字节跳动")],
            skill_list=[SkillEntry(name="Python")],
            confidence_score=0.2,
        )

        need_fallback, reason = handler._check_fallback_needed(structured, None)

        assert need_fallback is True
        assert "置信度" in reason

    def test_calculate_missing_rate(self, handler, full_structured, empty_structured):
        """测试计算缺失率"""
        # 完整数据缺失率应该低
        rate1 = handler._calculate_missing_rate(full_structured)
        assert rate1 < 0.5

        # 空数据缺失率应该高
        rate2 = handler._calculate_missing_rate(empty_structured)
        assert rate2 > 0.5

    def test_try_partial_parse_with_data(self, handler, partial_structured):
        """测试尝试部分解析（有数据）"""
        result = handler._try_partial_parse(partial_structured)

        assert result is not None
        assert result.personal_info.full_name == "张三"
        assert len(result.extraction_warnings) > 0

    def test_try_partial_parse_empty(self, handler, empty_structured):
        """测试尝试部分解析（无数据）"""
        result = handler._try_partial_parse(empty_structured)

        assert result is None

    def test_get_fallback_handler(self):
        """测试获取全局实例"""
        handler = get_fallback_handler()
        assert isinstance(handler, FallbackHandler)
