"""
智能招聘 RAG 推荐系统 - Resume Repository 测试
"""

import pytest

from src.resume_store.models import (
    EducationEntry,
    ExperienceEntry,
    PersonalInfo,
    ResumeCreateRequest,
    ResumeStatus,
    ResumeUpdateRequest,
    SkillEntry,
)
from src.resume_store.repository import ResumeRepository, get_resume_repository


@pytest.fixture
def repository():
    """创建数据仓库实例"""
    return ResumeRepository()


@pytest.fixture
def sample_request():
    """示例创建请求"""
    return ResumeCreateRequest(
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
    )


class TestResumeRepository:
    """ResumeRepository 测试"""

    def test_mask_phone(self, repository):
        """测试手机号脱敏"""
        assert repository._mask_phone("13800138000") == "138****8000"
        assert repository._mask_phone("1380013") == "138****013"
        assert repository._mask_phone("") == ""
        assert repository._mask_phone("123") == "123"

    def test_mask_email(self, repository):
        """测试邮箱脱敏"""
        assert repository._mask_email("test@example.com") == "tes***@example.com"
        assert repository._mask_email("ab@example.com") == "ab***@example.com"
        assert repository._mask_email("") == ""
        assert repository._mask_email("invalid") == "invalid"

    def test_to_response_desensitize(self, repository, sample_request):
        """测试响应转换（脱敏）"""
        from src.resume_store.models import ResumeSchema

        resume = ResumeSchema(
            user_id="user123",
            personal_info=sample_request.personal_info,
            education_list=sample_request.education_list,
            experience_list=sample_request.experience_list,
            skill_list=sample_request.skill_list,
        )

        response = repository._to_response(resume, desensitize=True)

        # 验证手机号已脱敏
        assert response.personal_info.phone == "138****8000"

        # 验证邮箱已脱敏（zhangsan -> zha***）
        assert response.personal_info.email == "zha***@example.com"

    def test_to_response_no_desensitize(self, repository, sample_request):
        """测试响应转换（不脱敏）"""
        from src.resume_store.models import ResumeSchema

        resume = ResumeSchema(
            user_id="user123",
            personal_info=sample_request.personal_info,
            education_list=sample_request.education_list,
            experience_list=sample_request.experience_list,
            skill_list=sample_request.skill_list,
        )

        response = repository._to_response(resume, desensitize=False)

        # 验证手机号未脱敏
        assert response.personal_info.phone == "13800138000"

        # 验证邮箱未脱敏
        assert response.personal_info.email == "zhangsan@example.com"

    def test_get_resume_repository(self):
        """测试获取全局实例"""
        repository = get_resume_repository()
        assert isinstance(repository, ResumeRepository)


class TestResumeRepositoryIntegration:
    """ResumeRepository 集成测试（需要 MongoDB）"""

    @pytest.mark.skip(reason="需要 MongoDB 连接")
    def test_create_and_get(self, repository, sample_request):
        """测试创建和获取简历"""
        pass

    @pytest.mark.skip(reason="需要 MongoDB 连接")
    def test_list_desensitized(self, repository):
        """测试列表查询（脱敏）"""
        pass
