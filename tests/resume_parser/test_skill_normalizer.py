"""
智能招聘 RAG 推荐系统 - Skill 标准化测试
"""

import pytest

from src.resume_parser.skill_normalizer import (
    NormalizedSkill,
    SkillNormalizationResult,
    SkillNormalizer,
    get_skill_normalizer,
)


@pytest.fixture
def normalizer():
    """创建 Skill 标准化器实例"""
    return SkillNormalizer()


class TestNormalizedSkill:
    """NormalizedSkill 测试"""

    def test_create_normalized_skill(self):
        """测试创建标准化技能"""
        skill = NormalizedSkill(
            raw_name="python",
            normalized_name="Python",
            category="编程语言",
            confidence=1.0,
            is_recognized=True,
        )

        assert skill.raw_name == "python"
        assert skill.normalized_name == "Python"
        assert skill.category == "编程语言"
        assert skill.confidence == 1.0
        assert skill.is_recognized is True


class TestSkillNormalizer:
    """SkillNormalizer 测试"""

    def test_normalize_exact_match(self, normalizer):
        """测试精确匹配"""
        skills = ["Python", "Java", "JavaScript"]
        result = normalizer.normalize(skills)

        assert isinstance(result, SkillNormalizationResult)
        assert result.total_skills == 3
        assert len(result.normalized_skills) == 3

        # 验证标准化结果
        python_skill = next(
            s for s in result.normalized_skills if s.raw_name == "Python"
        )
        assert python_skill.normalized_name == "Python"
        assert python_skill.is_recognized is True

    def test_normalize_alias_match(self, normalizer):
        """测试别名匹配"""
        skills = ["JS", "PyTorch", "K8s"]
        result = normalizer.normalize(skills)

        # JS 应该匹配到 JavaScript
        js_skill = next(
            s for s in result.normalized_skills if s.raw_name == "JS"
        )
        assert js_skill.normalized_name == "JavaScript"
        assert js_skill.is_recognized is True

        # PyTorch 应该匹配到 PyTorch
        pytorch_skill = next(
            s for s in result.normalized_skills if s.raw_name == "PyTorch"
        )
        assert pytorch_skill.normalized_name == "PyTorch"

    def test_normalize_unrecognized(self, normalizer):
        """测试未识别技能"""
        skills = ["SomeUnknownSkill", "AnotherUnknown"]
        result = normalizer.normalize(skills)

        assert len(result.unrecognized_skills) == 2
        assert "SomeUnknownSkill" in result.unrecognized_skills

        # 未识别技能仍然保留在结果中
        unrecognized = next(
            s for s in result.normalized_skills if s.raw_name == "SomeUnknownSkill"
        )
        assert unrecognized.is_recognized is False
        assert unrecognized.category == "unrecognized"

    def test_normalize_empty_list(self, normalizer):
        """测试空列表"""
        result = normalizer.normalize([])
        assert result.total_skills == 0
        assert result.normalized_skills == []
        assert result.unrecognized_skills == []

    def test_normalize_mixed(self, normalizer):
        """测试混合列表"""
        skills = ["Python", "SomeUnknown", "Java", "AnotherUnknown"]
        result = normalizer.normalize(skills)

        assert result.total_skills == 4
        assert len(result.unrecognized_skills) == 2
        assert len(result.normalized_skills) == 4

    def test_fuzzy_match(self, normalizer):
        """测试模糊匹配"""
        # 设置较低的阈值以测试模糊匹配
        normalizer.set_fuzzy_threshold(0.6)

        skills = ["Pythn", "Javscript"]  # 拼写错误
        result = normalizer.normalize(skills)

        # 应该能匹配到 Python 和 JavaScript
        pythn_skill = next(
            s for s in result.normalized_skills if s.raw_name == "Pythn"
        )
        assert pythn_skill.is_recognized is True
        assert pythn_skill.normalized_name == "Python"

    def test_clean_skill_name(self, normalizer):
        """测试清理技能名称"""
        # 测试移除版本号
        cleaned = normalizer._clean_skill_name("Python3.9")
        assert "3.9" not in cleaned

        # 测试移除括号
        cleaned = normalizer._clean_skill_name("Java(JDK)")
        assert "(JDK)" not in cleaned

    def test_add_custom_mapping(self, normalizer):
        """测试添加自定义映射"""
        normalizer.add_custom_mapping(
            "my_custom_skill",
            "My Custom Skill",
            "自定义分类",
        )

        skills = ["my_custom_skill"]
        result = normalizer.normalize(skills)

        custom_skill = result.normalized_skills[0]
        assert custom_skill.normalized_name == "My Custom Skill"
        assert custom_skill.category == "自定义分类"
        assert custom_skill.is_recognized is True

    def test_set_fuzzy_threshold(self, normalizer):
        """测试设置模糊匹配阈值"""
        normalizer.set_fuzzy_threshold(0.9)
        assert normalizer.fuzzy_threshold == 0.9

        # 测试边界值
        normalizer.set_fuzzy_threshold(1.5)
        assert normalizer.fuzzy_threshold == 1.0

        normalizer.set_fuzzy_threshold(-0.5)
        assert normalizer.fuzzy_threshold == 0.0

    def test_get_skill_normalizer(self):
        """测试获取全局实例"""
        normalizer = get_skill_normalizer()
        assert isinstance(normalizer, SkillNormalizer)


class TestSkillNormalizationResult:
    """SkillNormalizationResult 测试"""

    def test_create_result(self):
        """测试创建结果"""
        result = SkillNormalizationResult(
            normalized_skills=[
                NormalizedSkill(
                    raw_name="Python",
                    normalized_name="Python",
                    is_recognized=True,
                )
            ],
            unrecognized_skills=[],
            total_skills=1,
        )

        assert result.total_skills == 1
        assert len(result.normalized_skills) == 1
        assert len(result.unrecognized_skills) == 0
