"""
智能招聘 RAG 推荐系统 - 简历存储测试
"""

from datetime import datetime

import pytest

from src.resume_store.encryption import PIIEncryptor, get_encryptor
from src.resume_store.models import (
    EducationEntry,
    ExperienceEntry,
    PersonalInfo,
    ResumeCreateRequest,
    ResumeSchema,
    ResumeStatus,
    SkillEntry,
)


class TestPIIEncryptor:
    """PII 加密器测试"""

    @pytest.fixture
    def encryptor(self):
        """创建加密器实例"""
        return PIIEncryptor()

    def test_encrypt_decrypt_roundtrip(self, encryptor):
        """测试加密解密往返"""
        plaintext = "13800138000"
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_empty_string(self, encryptor):
        """测试加密空字符串"""
        assert encryptor.encrypt("") == ""
        assert encryptor.decrypt("") == ""

    def test_encrypt_email(self, encryptor):
        """测试加密邮箱"""
        email = "test@example.com"
        encrypted = encryptor.encrypt(email)
        decrypted = encryptor.decrypt(encrypted)
        assert decrypted == email

    def test_mask_phone(self, encryptor):
        """测试手机号脱敏"""
        assert encryptor.mask_phone("13800138000") == "138****8000"
        assert encryptor.mask_phone("1380013") == "138****013"
        assert encryptor.mask_phone("") == ""
        assert encryptor.mask_phone("123") == "123"

    def test_mask_email(self, encryptor):
        """测试邮箱脱敏"""
        assert encryptor.mask_email("test@example.com") == "tes***@example.com"
        assert encryptor.mask_email("ab@example.com") == "ab***@example.com"
        assert encryptor.mask_email("") == ""
        assert encryptor.mask_email("invalid") == "invalid"

    def test_encrypt_pii_fields(self, encryptor):
        """测试加密 PII 字段"""
        data = {
            "name": "张三",
            "phone": "13800138000",
            "email": "test@example.com",
        }

        encrypted = encryptor.encrypt_pii_fields(data)

        # 验证 phone 和 email 被加密
        assert encrypted["phone"] != data["phone"]
        assert encrypted["email"] != data["email"]
        assert encrypted["name"] == data["name"]

        # 验证可以解密回来
        decrypted = encryptor.decrypt_pii_fields(encrypted)
        assert decrypted["phone"] == data["phone"]
        assert decrypted["email"] == data["email"]

    def test_encrypt_pii_fields_with_none(self, encryptor):
        """测试加密包含 None 的 PII 字段"""
        data = {
            "name": "张三",
            "phone": None,
            "email": None,
        }

        encrypted = encryptor.encrypt_pii_fields(data)
        assert encrypted["phone"] is None
        assert encrypted["email"] is None


class TestResumeSchema:
    """ResumeSchema 测试"""

    def test_create_resume_schema(self):
        """测试创建 ResumeSchema"""
        resume = ResumeSchema(
            user_id="user123",
            personal_info=PersonalInfo(
                full_name="张三",
                phone="13800138000",
                email="test@example.com",
            ),
            education_list=[
                EducationEntry(
                    school="北京大学",
                    degree="本科",
                    major="计算机科学与技术",
                ),
            ],
            experience_list=[
                ExperienceEntry(
                    company="字节跳动",
                    title="后端工程师",
                ),
            ],
            skill_list=[
                SkillEntry(name="Python"),
                SkillEntry(name="Java"),
            ],
        )

        assert resume.user_id == "user123"
        assert resume.personal_info.full_name == "张三"
        assert len(resume.education_list) == 1
        assert len(resume.experience_list) == 1
        assert len(resume.skill_list) == 2
        assert resume.status == ResumeStatus.ACTIVE
        assert resume.id is not None

    def test_resume_to_mongodb_dict(self):
        """测试转换为 MongoDB 文档格式"""
        resume = ResumeSchema(
            user_id="user123",
            personal_info=PersonalInfo(full_name="张三"),
        )

        doc = resume.to_mongodb_dict()

        assert doc["id"] == resume.id
        assert doc["user_id"] == "user123"
        assert doc["personal_info"]["full_name"] == "张三"
        assert isinstance(doc["created_at"], str)
        assert isinstance(doc["updated_at"], str)

    def test_resume_from_mongodb_dict(self):
        """测试从 MongoDB 文档创建"""
        doc = {
            "id": "test-id",
            "user_id": "user123",
            "personal_info": {"full_name": "张三"},
            "education_list": [],
            "experience_list": [],
            "project_list": [],
            "skill_list": [],
            "status": "active",
            "created_at": "2026-06-23T22:00:00",
            "updated_at": "2026-06-23T22:00:00",
        }

        resume = ResumeSchema.from_mongodb_dict(doc)

        assert resume.id == "test-id"
        assert resume.user_id == "user123"
        assert resume.personal_info.full_name == "张三"
        assert isinstance(resume.created_at, datetime)


class TestResumeCreateRequest:
    """ResumeCreateRequest 测试"""

    def test_create_request(self):
        """测试创建请求"""
        request = ResumeCreateRequest(
            personal_info=PersonalInfo(
                full_name="张三",
                phone="13800138000",
            ),
            education_list=[
                EducationEntry(school="北京大学"),
            ],
        )

        assert request.personal_info.full_name == "张三"
        assert len(request.education_list) == 1

    def test_create_request_defaults(self):
        """测试创建请求默认值"""
        request = ResumeCreateRequest()

        assert request.personal_info.full_name is None
        assert len(request.education_list) == 0
        assert len(request.experience_list) == 0
        assert len(request.project_list) == 0
        assert len(request.skill_list) == 0
        assert request.raw_text is None
