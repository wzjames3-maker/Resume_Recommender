"""
智能招聘 RAG 推荐系统 - 简历数据模型

对齐 specs/resume-parser/02-data-model.md
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ResumeStatus(str, Enum):
    """简历状态"""

    ACTIVE = "active"  # 活跃
    ARCHIVED = "archived"  # 归档
    DELETED = "deleted"  # 已删除


class ParseStatus(str, Enum):
    """简历解析状态"""

    PENDING = "pending"  # 待解析
    PARSING = "parsing"  # 解析中
    SUCCESS = "success"  # 解析成功
    PARTIAL = "partial"  # 部分解析成功
    FAILED = "failed"  # 解析失败
    SKIPPED = "skipped"  # 文件已存在，跳过解析


class EducationEntry(BaseModel):
    """教育经历"""

    school: Optional[str] = Field(None, description="学校名称")
    degree: Optional[str] = Field(None, description="学历（本科/硕士/博士/大专）")
    major: Optional[str] = Field(None, description="专业")
    start_date: Optional[str] = Field(None, description="开始日期（YYYY-MM 或 YYYY）")
    end_date: Optional[str] = Field(None, description="结束日期（YYYY-MM 或 YYYY）")
    is_985: Optional[bool] = Field(None, description="是否 985 院校")
    is_211: Optional[bool] = Field(None, description="是否 211 院校")
    is_double_first_class: Optional[bool] = Field(None, description="是否双一流院校")
    gpa: Optional[float] = Field(None, description="GPA")
    description: Optional[str] = Field(None, description="其他描述")


class ExperienceEntry(BaseModel):
    """工作经历"""

    company: Optional[str] = Field(None, description="公司名称")
    title: Optional[str] = Field(None, description="职位名称")
    start_date: Optional[str] = Field(None, description="开始日期（YYYY-MM 或 YYYY）")
    end_date: Optional[str] = Field(None, description="结束日期（YYYY-MM 或 YYYY 或 至今）")
    is_current: Optional[bool] = Field(False, description="是否在职")
    description: Optional[str] = Field(None, description="工作描述")
    achievements: list[str] = Field(default_factory=list, description="工作成果列表")
    industry: Optional[str] = Field(None, description="所属行业")


class ProjectEntry(BaseModel):
    """项目经历"""

    name: Optional[str] = Field(None, description="项目名称")
    role: Optional[str] = Field(None, description="担任角色")
    start_date: Optional[str] = Field(None, description="开始日期")
    end_date: Optional[str] = Field(None, description="结束日期")
    description: Optional[str] = Field(None, description="项目描述")
    tech_stack: list[str] = Field(default_factory=list, description="技术栈")
    achievements: list[str] = Field(default_factory=list, description="项目成果")
    url: Optional[str] = Field(None, description="项目链接")


class SkillEntry(BaseModel):
    """技能"""

    name: str = Field(..., description="技能名称（标准化后）")
    category: Optional[str] = Field(None, description="技能分类")
    proficiency: Optional[str] = Field(None, description="熟练度（了解/熟悉/熟练/精通）")
    years_of_experience: Optional[int] = Field(None, ge=0, le=30, description="使用年限")
    original_names: list[str] = Field(default_factory=list, description="原始名称列表")


class PersonalInfo(BaseModel):
    """候选人个人信息"""

    full_name: Optional[str] = Field(None, description="姓名")
    phone: Optional[str] = Field(None, description="手机号（加密存储）")
    email: Optional[str] = Field(None, description="邮箱（加密存储）")
    city: Optional[str] = Field(None, description="所在城市")
    birth_year: Optional[int] = Field(None, ge=1900, le=2010, description="出生年份")
    gender: Optional[str] = Field(None, description="性别")
    years_of_experience: Optional[int] = Field(None, ge=0, le=50, description="工作年限")
    current_company: Optional[str] = Field(None, description="当前公司")
    current_title: Optional[str] = Field(None, description="当前职位")
    expected_city: Optional[str] = Field(None, description="期望工作城市")
    expected_salary_range: Optional[str] = Field(None, description="期望薪资范围")
    summary: Optional[str] = Field(None, description="个人简介/自我评价")


class ResumeMetadata(BaseModel):
    """简历解析元数据"""

    source_file_name: str = Field(..., description="原始文件名")
    source_file_type: str = Field(..., description="文件类型（pdf/docx/jpg/png/json）")
    source_file_size: int = Field(..., description="文件大小（字节）")
    parse_status: ParseStatus = Field(ParseStatus.PENDING, description="解析状态")
    parse_tool: Optional[str] = Field(None, description="文本提取工具")
    llm_model: Optional[str] = Field(None, description="LLM 模型名称")
    llm_tokens_used: Optional[int] = Field(None, description="LLM token 用量")
    parse_duration_ms: Optional[int] = Field(None, description="解析耗时（毫秒）")
    language: Optional[str] = Field(None, description="识别的语言（zh/en/mixed）")
    error_message: Optional[str] = Field(None, description="错误信息")
    created_at: Optional[str] = Field(None, description="解析时间（ISO 8601）")
    retry_count: int = Field(0, description="重试次数")
    file_md5: Optional[str] = Field(None, description="文件内容 MD5 哈希值")


class ResumeSchema(BaseModel):
    """简历完整结构化数据"""

    id: str = Field(default_factory=lambda: str(uuid4()), description="简历 ID (UUID)")
    user_id: str = Field(..., description="所属用户 ID")
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo, description="个人信息")
    education_list: list[EducationEntry] = Field(default_factory=list, description="教育经历列表")
    experience_list: list[ExperienceEntry] = Field(default_factory=list, description="工作经历列表")
    project_list: list[ProjectEntry] = Field(default_factory=list, description="项目经历列表")
    skill_list: list[SkillEntry] = Field(default_factory=list, description="技能列表")
    raw_text: Optional[str] = Field(None, description="原始解析文本")
    vector_id: Optional[str] = Field(None, description="Milvus 中的向量 ID")
    status: ResumeStatus = Field(ResumeStatus.ACTIVE, description="简历状态")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="更新时间")

    def to_mongodb_dict(self) -> dict:
        """转换为 MongoDB 文档格式"""
        data = self.model_dump()
        # 转换 datetime 为 ISO 格式字符串
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_mongodb_dict(cls, data: dict) -> "ResumeSchema":
        """从 MongoDB 文档创建 ResumeSchema"""
        # 转换 ISO 格式字符串为 datetime
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)


class ResumeCreateRequest(BaseModel):
    """创建简历请求"""

    personal_info: PersonalInfo = Field(default_factory=PersonalInfo, description="个人信息")
    education_list: list[EducationEntry] = Field(default_factory=list, description="教育经历列表")
    experience_list: list[ExperienceEntry] = Field(default_factory=list, description="工作经历列表")
    project_list: list[ProjectEntry] = Field(default_factory=list, description="项目经历列表")
    skill_list: list[SkillEntry] = Field(default_factory=list, description="技能列表")
    raw_text: Optional[str] = Field(None, description="原始解析文本")


class ResumeUpdateRequest(BaseModel):
    """更新简历请求"""

    personal_info: Optional[PersonalInfo] = Field(None, description="个人信息")
    education_list: Optional[list[EducationEntry]] = Field(None, description="教育经历列表")
    experience_list: Optional[list[ExperienceEntry]] = Field(None, description="工作经历列表")
    project_list: Optional[list[ProjectEntry]] = Field(None, description="项目经历列表")
    skill_list: Optional[list[SkillEntry]] = Field(None, description="技能列表")
    status: Optional[ResumeStatus] = Field(None, description="简历状态")


class ResumeResponse(BaseModel):
    """简历响应"""

    id: str = Field(..., description="简历 ID")
    user_id: str = Field(..., description="所属用户 ID")
    personal_info: PersonalInfo = Field(..., description="个人信息")
    education_list: list[EducationEntry] = Field(..., description="教育经历列表")
    experience_list: list[ExperienceEntry] = Field(..., description="工作经历列表")
    project_list: list[ProjectEntry] = Field(..., description="项目经历列表")
    skill_list: list[SkillEntry] = Field(..., description="技能列表")
    status: ResumeStatus = Field(..., description="简历状态")
    raw_text: Optional[str] = Field(None, description="原始解析文本")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class ResumeListResponse(BaseModel):
    """简历列表响应"""

    items: list[ResumeResponse] = Field(..., description="简历列表")
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    size: int = Field(..., description="每页数量")
