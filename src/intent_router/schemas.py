"""
智能招聘 RAG 推荐系统 - Intent Router 数据模型

对齐 specs/intent-router/02-data-model.md
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class IntentEnum(str, Enum):
    """系统支持的 10 类意图"""

    RECRUITMENT_SEARCH = "recruitment.search"  # 智能候选人检索
    RECRUITMENT_REFINE = "recruitment.refine"  # 多轮条件修正
    RECRUITMENT_COMPARE = "recruitment.compare"  # 候选人对比
    CANDIDATE_LOOKUP = "candidate.lookup"  # 候选人详情查看
    RESUME_UPLOAD = "resume.upload"  # 简历上传
    RESUME_MANAGE = "resume.manage"  # 简历管理
    KNOWLEDGE_QA = "knowledge.qa"  # 知识问答
    ANALYTICS = "analytics"  # 数据统计
    CHAT = "chat"  # 闲聊
    FALLBACK = "fallback"  # 兜底


class ExperienceOp(str, Enum):
    """年限比较运算符"""

    GTE = ">="
    LTE = "<="
    EQ = "="
    BETWEEN = "between"


class AgeOp(str, Enum):
    """年龄比较运算符"""

    GTE = ">="
    LTE = "<="
    BETWEEN = "between"


class SalaryOp(str, Enum):
    """薪资比较运算符"""

    GTE = ">="
    LTE = "<="
    BETWEEN = "between"


class EducationLevel(str, Enum):
    """学历等级"""

    HIGH_SCHOOL = "高中"
    COLLEGE = "大专"
    BACHELOR = "本科"
    MASTER = "硕士"
    DOCTOR = "博士"
    _985 = "985"
    _211 = "211"
    DOUBLE_FIRST_CLASS = "双一流"


class Gender(str, Enum):
    """性别"""

    MALE = "男"
    FEMALE = "女"


class JobType(str, Enum):
    """用工形式"""

    FULL_TIME = "全职"
    PART_TIME = "兼职"
    OUTSOURCE = "外包"
    INTERN = "实习"


class SortBy(str, Enum):
    """排序字段"""

    SCORE = "score"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    RECENT = "recent"


class Order(str, Enum):
    """排序方向"""

    ASC = "asc"
    DESC = "desc"


class CandidateSlot(BaseModel):
    """候选人属性 Slots — 从用户输入中提取"""

    job_title: Optional[str] = Field(None, description="目标岗位/职位，如 Java工程师、算法工程师")
    skills: Optional[List[str]] = Field(None, description="技能列表，如 ['Java', 'Spring Boot']")
    experience: Optional[float] = Field(None, description="工作年限，如 5")
    experience_op: Optional[ExperienceOp] = Field(None, description="年限比较运算符")
    education: Optional[EducationLevel] = Field(None, description="学历要求")
    gender: Optional[Gender] = Field(None, description="性别要求")
    age: Optional[int] = Field(None, description="年龄要求")
    age_op: Optional[AgeOp] = Field(None, description="年龄比较运算符")
    city: Optional[str] = Field(None, description="工作城市，如 杭州、北京")
    industry: Optional[str] = Field(None, description="行业经验，如 电商、金融")
    company: Optional[str] = Field(None, description="公司经历，如 阿里巴巴")
    school: Optional[str] = Field(None, description="毕业学校，如 清华大学")
    salary: Optional[float] = Field(None, description="期望薪资（元/月）")
    salary_op: Optional[SalaryOp] = Field(None, description="薪资比较运算符")
    language: Optional[List[str]] = Field(None, description="语言能力，如 ['英语六级', '日语N1']")
    certificate: Optional[List[str]] = Field(None, description="证书资质，如 ['PMP', 'AWS认证']")
    job_type: Optional[JobType] = Field(None, description="用工形式")

    # 排除条件
    exclude_job_type: Optional[List[str]] = Field(None, description="排除的用工形式")
    exclude_company: Optional[List[str]] = Field(None, description="排除的公司")
    exclude_city: Optional[List[str]] = Field(None, description="排除的城市")
    exclude_skills: Optional[List[str]] = Field(None, description="排除的技能")


class QuerySlot(BaseModel):
    """查询控制 Slots — 控制推荐结果的呈现"""

    count: int = Field(default=10, ge=1, le=100, description="推荐数量，默认 10")
    sort_by: SortBy = Field(default=SortBy.SCORE, description="排序字段，默认按匹配分")
    order: Order = Field(default=Order.DESC, description="排序方向，默认降序")
    page: int = Field(default=1, ge=1, description="页码，默认 1")
    top_k: int = Field(default=50, ge=1, le=500, description="检索召回数量，默认 50")


class IntentResult(BaseModel):
    """意图识别结果 — Intent Router 的核心输出"""

    intent: IntentEnum = Field(description="识别的意图类型")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度 0.0~1.0")
    candidate_slots: CandidateSlot = Field(
        default_factory=CandidateSlot,
        description="候选人属性 Slots",
    )
    query_slots: QuerySlot = Field(
        default_factory=QuerySlot,
        description="查询控制 Slots",
    )
    raw_query: str = Field(description="用户原始输入")
    reasoning: str = Field(default="", description="LLM 的推理说明（调试用）")


class ConversationContext(BaseModel):
    """对话上下文 — 从 Conversation Memory 模块获取"""

    conversation_id: str = Field(description="会话唯一标识")
    turn_count: int = Field(default=0, description="当前对话轮次")
    last_query: Optional[dict] = Field(None, description="上一次查询的完整 Slots")
    last_filters: Optional[dict] = Field(None, description="上一次生效的过滤条件")
    last_candidates: Optional[List[dict]] = Field(None, description="上一次推荐的候选人列表")
    last_intent: Optional[IntentEnum] = Field(None, description="上一次识别的意图")
    intent_history: List[IntentEnum] = Field(
        default_factory=list, description="历史意图序列"
    )
