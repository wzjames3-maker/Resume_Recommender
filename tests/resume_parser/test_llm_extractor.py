"""
智能招聘 RAG 推荐系统 - LLM 结构化提取测试
"""

import pytest

from src.resume_parser.llm_extractor import (
    ExtractionMetrics,
    ExtractionWarning,
    LLMExtractor,
    ResumeStructured,
    get_llm_extractor,
)


@pytest.fixture
def extractor():
    """创建 LLM 提取器实例"""
    return LLMExtractor()


class TestResumeStructured:
    """ResumeStructured 测试"""

    def test_create_structured(self):
        """测试创建结构化数据"""
        from src.resume_store.models import PersonalInfo

        data = ResumeStructured(
            personal_info=PersonalInfo(full_name="张三"),
            confidence_score=0.9,
        )

        assert data.personal_info.full_name == "张三"
        assert data.education_list == []
        assert data.experience_list == []
        assert data.skill_list == []
        assert data.confidence_score == 0.9
        assert data.extraction_warnings == []

    def test_structured_defaults(self):
        """测试默认值"""
        data = ResumeStructured()
        assert data.personal_info.full_name is None
        assert data.confidence_score == 1.0


class TestExtractionMetrics:
    """ExtractionMetrics 测试"""

    def test_create_metrics(self):
        """测试创建指标"""
        metrics = ExtractionMetrics(
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            duration_ms=1500,
            retry_count=1,
        )

        assert metrics.input_tokens == 100
        assert metrics.output_tokens == 200
        assert metrics.total_tokens == 300
        assert metrics.duration_ms == 1500
        assert metrics.retry_count == 1


class TestExtractionWarning:
    """ExtractionWarning 测试"""

    def test_create_warning(self):
        """测试创建警告"""
        warning = ExtractionWarning(
            field="phone",
            message="无法识别手机号",
            confidence=0.5,
        )

        assert warning.field == "phone"
        assert warning.message == "无法识别手机号"
        assert warning.confidence == 0.5


class TestLLMExtractor:
    """LLMExtractor 测试"""

    def test_build_function_schema(self, extractor):
        """测试构建 Function Schema"""
        schema = extractor._build_function_schema()

        assert schema["name"] == "extract_resume"
        assert "parameters" in schema
        assert "properties" in schema["parameters"]

        # 验证必需字段
        required = schema["parameters"]["required"]
        assert "personal_info" in required
        assert "education_list" in required
        assert "experience_list" in required
        assert "skill_list" in required

    def test_build_prompt(self, extractor):
        """测试构建 Prompt"""
        text = "张三，北京大学，计算机科学与技术，本科"
        prompt = extractor._build_prompt(text)

        assert text in prompt
        assert "提取" in prompt
        assert "结构化" in prompt

    def test_parse_result(self, extractor):
        """测试解析结果"""
        result = {
            "personal_info": {
                "full_name": "张三",
                "phone": "13800138000",
                "email": "zhangsan@example.com",
            },
            "education_list": [
                {
                    "school": "北京大学",
                    "degree": "本科",
                    "major": "计算机科学与技术",
                }
            ],
            "experience_list": [
                {
                    "company": "字节跳动",
                    "title": "后端工程师",
                }
            ],
            "skill_list": [
                {"name": "Python"},
                {"name": "Java"},
            ],
            "confidence_score": 0.9,
        }

        structured = extractor._parse_result(result)

        assert structured.personal_info.full_name == "张三"
        assert structured.personal_info.phone == "13800138000"
        assert len(structured.education_list) == 1
        assert structured.education_list[0].school == "北京大学"
        assert len(structured.experience_list) == 1
        assert len(structured.skill_list) == 2
        assert structured.confidence_score == 0.9

    def test_parse_result_empty(self, extractor):
        """测试解析空结果"""
        result = {
            "personal_info": {},
            "education_list": [],
            "experience_list": [],
            "skill_list": [],
        }

        structured = extractor._parse_result(result)

        assert structured.personal_info.full_name is None
        assert structured.education_list == []
        assert structured.experience_list == []
        assert structured.skill_list == []

    def test_fallback_result(self, extractor):
        """测试降级结果"""
        error_message = "API 调用失败"
        result = extractor._fallback_result(error_message)

        assert result.personal_info.full_name is None
        assert result.education_list == []
        assert result.experience_list == []
        assert result.skill_list == []
        assert result.confidence_score == 0.0
        assert len(result.extraction_warnings) == 1
        assert error_message in result.extraction_warnings[0].message

    def test_get_llm_extractor(self):
        """测试获取全局实例"""
        extractor = get_llm_extractor()
        assert isinstance(extractor, LLMExtractor)


class TestLLMExtractorIntegration:
    """LLM 提取器集成测试（需要实际 API 调用）"""

    @pytest.mark.skip(reason="需要实际 API 调用")
    def test_extract_from_text(self, extractor):
        """测试从文本提取（需要实际 API）"""
        text = """
        张三
        电话：13800138000
        邮箱：zhangsan@example.com

        教育经历
        2018-2022 北京大学 计算机科学与技术 本科

        工作经历
        2022-至今 字节跳动 后端工程师
        - 负责推荐系统开发

        技能
        Python, Java, Go
        """

        result = extractor.extract(text)

        assert result.personal_info.full_name == "张三"
        assert len(result.education_list) > 0
        assert len(result.experience_list) > 0
        assert len(result.skill_list) > 0
