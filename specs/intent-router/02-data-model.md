<!-- Module: intent-router -->
<!-- Spec Layer: 02 - Data Model -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 数据模型：Intent Router（意图路由模块）

## 模型总览

| 模型 | 类型 | 用途 |
|------|------|------|
| IntentEnum | Enum | 10 类 Intent 枚举 |
| ExperienceOp | Enum | 年限比较运算符 |
| SortBy | Enum | 排序字段 |
| Order | Enum | 排序方向 |
| EducationLevel | Enum | 学历等级 |
| Gender | Enum | 性别 |
| JobType | Enum | 用工形式 |
| CandidateSlot | Pydantic Model | 候选人属性 Slots（17 字段） |
| QuerySlot | Pydantic Model | 查询控制 Slots（5 字段） |
| IntentResult | Pydantic Model | 意图识别结果 |
| ConversationContext | Pydantic Model | 对话上下文 |
| IntentRouterState | TypedDict | LangGraph State |

---

## 1. IntentEnum

```python
from enum import Enum

class IntentEnum(str, Enum):
    """系统支持的 10 类意图"""
    RECRUITMENT_SEARCH = "recruitment.search"
    RECRUITMENT_REFINE = "recruitment.refine"
    RECRUITMENT_COMPARE = "recruitment.compare"
    CANDIDATE_LOOKUP = "candidate.lookup"
    RESUME_UPLOAD = "resume.upload"
    RESUME_MANAGE = "resume.manage"
    KNOWLEDGE_QA = "knowledge.qa"
    ANALYTICS = "analytics"
    CHAT = "chat"
    FALLBACK = "fallback"
```

**设计说明**：
- 继承 `str, Enum` 以便 JSON 序列化
- 值与 02-intent-inventory.md 中的标识完全一致

---

## 2. 辅助枚举

```python
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
```

---

## 3. CandidateSlot

候选人属性 Slot，对应 03-slot-definition.md 中的 17 个字段。

```python
from typing import Optional
from pydantic import BaseModel, Field

class CandidateSlot(BaseModel):
    """候选人属性 Slots — 从用户输入中提取"""
    job_title: Optional[str] = Field(None, description="目标岗位/职位，如 Java工程师、算法工程师")
    skills: Optional[list[str]] = Field(None, description="技能列表，如 ['Java', 'Spring Boot']")
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
    language: Optional[list[str]] = Field(None, description="语言能力，如 ['英语六级', '日语N1']")
    certificate: Optional[list[str]] = Field(None, description="证书资质，如 ['PMP', 'AWS认证']")
    job_type: Optional[JobType] = Field(None, description="用工形式")

    # 排除条件（动态字段，由 "不要XX" 表达生成）
    exclude_job_type: Optional[list[str]] = Field(None, description="排除的用工形式")
    exclude_company: Optional[list[str]] = Field(None, description="排除的公司")
    exclude_city: Optional[list[str]] = Field(None, description="排除的城市")
    exclude_skills: Optional[list[str]] = Field(None, description="排除的技能")
```

**设计说明**：
- 所有字段为 Optional — 用户未提及的 Slot 不填充默认值
- 排除条件使用 `exclude_` 前缀的动态字段
- Pydantic Field description 作为 LLM Function Calling 的参数描述

---

## 4. QuerySlot

查询控制参数，控制推荐结果的呈现方式。

```python
class QuerySlot(BaseModel):
    """查询控制 Slots — 控制推荐结果的呈现"""
    count: int = Field(default=10, ge=1, le=100, description="推荐数量，默认 10")
    sort_by: SortBy = Field(default=SortBy.SCORE, description="排序字段，默认按匹配分")
    order: Order = Field(default=Order.DESC, description="排序方向，默认降序")
    page: int = Field(default=1, ge=1, description="页码，默认 1")
    top_k: int = Field(default=50, ge=1, le=500, description="检索召回数量，默认 50")
```

**设计说明**：
- 所有字段有默认值 — 未指定时使用默认值
- `count` 有范围约束（1~100）
- `top_k` 是内部检索参数，不暴露给普通用户

---

## 5. IntentResult

意图识别的核心输出结构，包含 Intent、置信度、提取的 Slots。

```python
class IntentResult(BaseModel):
    """意图识别结果 — Intent Router 的核心输出"""
    intent: IntentEnum = Field(description="识别的意图类型")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度 0.0~1.0")
    candidate_slots: CandidateSlot = Field(
        default_factory=CandidateSlot,
        description="候选人属性 Slots"
    )
    query_slots: QuerySlot = Field(
        default_factory=QuerySlot,
        description="查询控制 Slots"
    )
    raw_query: str = Field(description="用户原始输入")
    reasoning: str = Field(default="", description="LLM 的推理说明（调试用）")
```

**设计说明**：
- `confidence` 有范围约束（0.0~1.0）
- `candidate_slots` 和 `query_slots` 使用默认工厂，确保始终有值
- `reasoning` 字段用于调试和 Audit Log，不参与业务逻辑

---

## 6. ConversationContext

从 Conversation Memory 获取的对话上下文。

```python
class ConversationContext(BaseModel):
    """对话上下文 — 从 Conversation Memory 模块获取"""
    conversation_id: str = Field(description="会话唯一标识")
    turn_count: int = Field(default=0, description="当前对话轮次")
    last_query: Optional[dict] = Field(None, description="上一次查询的完整 Slots")
    last_filters: Optional[dict] = Field(None, description="上一次生效的过滤条件")
    last_candidates: Optional[list[dict]] = Field(None, description="上一次推荐的候选人列表")
    last_intent: Optional[IntentEnum] = Field(None, description="上一次识别的意图")
    intent_history: list[IntentEnum] = Field(default_factory=list, description="历史意图序列")
```

---

## 7. IntentRouterState（LangGraph State）

LangGraph StateGraph 的状态定义，贯穿整个 Intent Router 的执行流程。

```python
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage

class IntentRouterState(TypedDict):
    """LangGraph State — Intent Router 的状态定义"""
    # 用户输入
    messages: Annotated[list[BaseMessage], "对话消息列表"]
    raw_query: str                            # 当前用户输入的原始文本

    # 对话上下文（从 Conversation Memory 获取）
    conversation_context: ConversationContext  # 对话上下文

    # 意图识别结果
    intent_result: IntentResult               # Intent + Confidence + Slots

    # 路由目标
    workflow_name: str                        # 路由目标 Workflow 名称

    # 合并后的 Slots（refine 场景下使用）
    merged_slots: dict                        # 合并后的最终 Slots

    # 元信息
    is_fallback: bool                         # 是否触发 Fallback
    audit_log: dict                           # Audit Log 数据
    error: str | None                         # 错误信息
```

**State Graph 流转**：

```
START
  │
  ▼
┌──────────────────┐
│ fetch_context    │  ← 从 Conversation Memory 获取上下文
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ classify_intent  │  ← LLM Function Call 识别 Intent + 提取 Slots
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ validate_result  │  ← Pydantic 校验 + 置信度检查
└────────┬─────────┘
         │
    ┌────▼────┐
    │ conf    │
    │ >= 0.6? │
    └──┬───┬──┘
   Yes │   │ No
       ▼   ▼
┌────────┐ ┌──────────┐
│ merge  │ │ fallback │
│ slots  │ │ handler  │
└───┬────┘ └──────────┘
    │
    ▼
┌──────────────────┐
│ write_audit_log  │  ← 写入 Audit Log
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ route_intent     │  ← Conditional Edge 分发到 Workflow
└──────────────────┘
```

---

## 8. LLM Function Calling Schema

用于 LLM Structured Output 的 Pydantic Schema，确保 LLM 输出符合预期格式。

```python
class IntentClassificationOutput(BaseModel):
    """LLM Function Calling 输出 Schema"""
    intent: IntentEnum = Field(description="识别的意图类型")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度 0.0~1.0")
    candidate_slots: CandidateSlot = Field(description="从输入中提取的候选人属性 Slots")
    query_slots: QuerySlot = Field(description="从输入中提取的查询控制 Slots")
    reasoning: str = Field(description="推理过程说明，解释为什么识别为此意图")
```

**使用方式**：

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="deepseek-chat", base_url="https://api.deepseek.com")
structured_llm = llm.with_structured_output(IntentClassificationOutput)

result = await structured_llm.ainvoke(messages)
# result.intent, result.confidence, result.candidate_slots, ...
```

---

## 9. AuditLogEntry

写入 Audit Log 的结构。

```python
from datetime import datetime

class AuditLogEntry(BaseModel):
    """Audit Log 记录"""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    conversation_id: str
    user_id: str
    raw_query: str
    detected_intent: str
    confidence: float
    extracted_slots: dict
    latency_ms: int
    llm_model: str
    llm_tokens_used: int
    is_fallback: bool = False
    error: Optional[str] = None
```
