<!-- Module: recommendation-engine -->
<!-- Spec Layer: 02 - Data Model -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 数据模型：Recommendation Engine

## 模型总览

本模块定义 4 个核心 Pydantic Schema，均为内部数据结构，不直接持久化到数据库。

```
┌─────────────────┐     ┌─────────────────┐
│  RetrievalResult │────>│  RankingResult   │
│  (检索阶段产出)   │     │  (排序阶段产出)   │
└─────────────────┘     └─────────────────┘
         │
         │ 过滤条件
         ▼
┌─────────────────┐     ┌─────────────────┐
│  FilterCriteria  │     │  WeightConfig    │
│  (过滤条件)       │     │  (权重配置)       │
└─────────────────┘     └─────────────────┘
```

---

## 1. RetrievalResult

**用途**: Hybrid Retrieval（REQ-003）阶段产出的候选结果，每个候选人的检索维度分数。

```python
from pydantic import BaseModel, Field
from typing import Optional


class RetrievalResult(BaseModel):
    """检索阶段的候选结果"""

    resume_id: str = Field(
        ...,
        description="简历唯一标识，对应 resume-store 中的 resume_id"
    )
    candidate_id: str = Field(
        ...,
        description="候选人唯一标识，用于去重（REQ-010）"
    )
    dense_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Dense 向量检索的相似度分数（COSINE），范围 0~1"
    )
    sparse_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Sparse 向量检索的分数（BM25 风格），下界 0，上界不固定"
    )
    hybrid_score: float = Field(
        ...,
        ge=0.0,
        description="RRF 合并后的混合分数，下界 0，上界不固定"
    )
    metadata: RetrievalMetadata = Field(
        default_factory=RetrievalMetadata,
        description="检索元数据"
    )


class RetrievalMetadata(BaseModel):
    """检索元数据"""

    dense_rank: Optional[int] = Field(
        default=None,
        ge=1,
        description="在 Dense 结果中的排名（1-based）"
    )
    sparse_rank: Optional[int] = Field(
        default=None,
        ge=1,
        description="在 Sparse 结果中的排名（1-based）"
    )
    rerank_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="BGE Reranker 打分，范围 0~1，未 Rerank 时为 None"
    )
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| resume_id | str | 是 | 简历 ID，全局唯一，对应 resume-store |
| candidate_id | str | 是 | 候选人 ID，一人可能有多份简历 |
| dense_score | float? | 否 | Dense 检索相似度（0~1），仅 Dense 检索时有值 |
| sparse_score | float? | 否 | Sparse 检索分数（>=0），仅 Sparse 检索时有值 |
| hybrid_score | float | 是 | RRF 合并分数，最低为 0 |
| metadata.dense_rank | int? | 否 | Dense 结果排名 |
| metadata.sparse_rank | int? | 否 | Sparse 结果排名 |
| metadata.rerank_score | float? | 否 | Reranker 分数（0~1），Rerank 后填充 |

### 生命周期

```
Dense Retrieval  →  RetrievalResult(dense_score, dense_rank)
Sparse Retrieval →  RetrievalResult(sparse_score, sparse_rank)
Hybrid Merge     →  RetrievalResult(hybrid_score = RRF(dense_rank, sparse_rank))
Rerank           →  RetrievalResult.metadata.rerank_score = reranker_output
```

---

## 2. RankingResult

**用途**: 排序阶段（REQ-007, REQ-008, REQ-009）产出的最终推荐结果，包含评分、理由和技能匹配信息。

```python
from pydantic import BaseModel, Field
from typing import Optional


class ScoreBreakdown(BaseModel):
    """五维度评分拆解（REQ-009）"""

    skill_match: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="技能匹配度评分，0~100"
    )
    experience_match: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="工作经验匹配评分，0~100"
    )
    project_relevance: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="项目经历相关性评分，0~100"
    )
    industry_match: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="行业经验匹配评分，0~100"
    )
    education_match: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="教育背景匹配评分，0~100"
    )


class RankingResult(BaseModel):
    """排序阶段的最终推荐结果"""

    resume_id: str = Field(
        ...,
        description="简历唯一标识"
    )
    candidate_id: str = Field(
        ...,
        description="候选人唯一标识"
    )
    final_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="综合匹配分，0~100"
    )
    rank: int = Field(
        ...,
        ge=1,
        description="最终排名（1-based）"
    )
    score_breakdown: ScoreBreakdown = Field(
        ...,
        description="五维度评分拆解"
    )
    reason: list[str] = Field(
        ...,
        min_length=2,
        description="推荐理由列表，至少 2 条，每条引用简历原文"
    )
    matched_skills: list[str] = Field(
        default_factory=list,
        description="匹配的技能列表"
    )
    missing_skills: list[str] = Field(
        default_factory=list,
        description="缺失的技能列表（Slots 中要求但候选人不具备）"
    )
    matched_experience: Optional[str] = Field(
        default=None,
        description="匹配的经验描述摘要"
    )
    degradation: Optional[str] = Field(
        default=None,
        description="降级标识，如 'reranker_fallback'，正常运行时为 None"
    )
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| resume_id | str | 是 | 简历 ID |
| candidate_id | str | 是 | 候选人 ID |
| final_score | float | 是 | 综合匹配分（0-100） |
| rank | int | 是 | 最终排名（1-based） |
| score_breakdown | ScoreBreakdown | 是 | 五维度独立评分 |
| reason | list[str] | 是 | 推荐理由（≥2 条） |
| matched_skills | list[str] | 否 | 匹配的技能 |
| missing_skills | list[str] | 否 | 缺失的技能 |
| matched_experience | str? | 否 | 匹配的经验摘要 |
| degradation | str? | 否 | 降级标识 |

### 与 RetrievalResult 的关系

```
RetrievalResult ──(Filter)──> ──(Rerank)──> ──(Score Calc + Reason Gen)──> RankingResult
```

一个 `RetrievalResult` 经过完整的 Filter → Rerank → Score → Reason 流程后，转化为一个 `RankingResult`。

---

## 3. WeightConfig

**用途**: 排序权重配置（REQ-007, REQ-011），支持不同岗位使用不同权重。

```python
from pydantic import BaseModel, Field, model_validator


class WeightConfig(BaseModel):
    """排序权重配置"""

    skill_weight: float = Field(
        default=0.40,
        ge=0.0,
        le=1.0,
        description="技能匹配度权重，默认 0.40"
    )
    experience_weight: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="工作经验匹配权重，默认 0.25"
    )
    project_weight: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="项目经历相关性权重，默认 0.20"
    )
    industry_weight: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description="行业经验匹配权重，默认 0.10"
    )
    education_weight: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="教育背景匹配权重，默认 0.05"
    )

    @model_validator(mode="after")
    def normalize_weights(self) -> "WeightConfig":
        """权重总和不为 1.0 时自动归一化（EC-007）"""
        total = (
            self.skill_weight
            + self.experience_weight
            + self.project_weight
            + self.industry_weight
            + self.education_weight
        )
        if abs(total - 1.0) > 0.001:
            self.skill_weight /= total
            self.experience_weight /= total
            self.project_weight /= total
            self.industry_weight /= total
            self.education_weight /= total
        return self
```

### 默认权重

| 维度 | 默认值 | 可配置 |
|------|--------|--------|
| skill_weight | 0.40 | 是 |
| experience_weight | 0.25 | 是 |
| project_weight | 0.20 | 是 |
| industry_weight | 0.10 | 是 |
| education_weight | 0.05 | 是 |

### 归一化规则（EC-007）

- 权重总和允许浮动（如 0.45 + 0.25 + 0.20 + 0.10 + 0.05 = 1.05）
- Pydantic validator 自动归一化：每个权重除以总和
- 归一化后权重和严格为 1.0

---

## 4. FilterCriteria

**用途**: Metadata Filter（REQ-004）的过滤条件，由 intent-router 的 Slots 转化而来。

```python
from pydantic import BaseModel, Field
from typing import Optional


class FilterCriteria(BaseModel):
    """Metadata Filter 过滤条件"""

    job_title: Optional[str] = Field(
        default=None,
        description="期望岗位，模糊匹配 + Soft Match"
    )
    skills: list[str] = Field(
        default_factory=list,
        description="要求的技能列表，Soft Match 匹配"
    )
    experience: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="要求的工作年限"
    )
    experience_op: str = Field(
        default=">=",
        pattern="^(>=|<=|==|between)$",
        description="年限比较运算符"
    )
    experience_max: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="年限上界，仅 experience_op='between' 时使用"
    )
    education: Optional[str] = Field(
        default=None,
        description="要求的最低学历：高中/大专/本科/硕士/博士"
    )
    gender: Optional[str] = Field(
        default=None,
        pattern="^(男|女)$",
        description="性别要求，需注意法律法规合规性（PRD O-001）"
    )
    age_min: Optional[int] = Field(
        default=None,
        ge=18,
        le=65,
        description="年龄下界"
    )
    age_max: Optional[int] = Field(
        default=None,
        ge=18,
        le=65,
        description="年龄上界"
    )
    city: Optional[str] = Field(
        default=None,
        description="要求的城市，精确匹配"
    )
    industry: Optional[str] = Field(
        default=None,
        description="要求的行业，模糊匹配"
    )
    company: Optional[str] = Field(
        default=None,
        description="要求的公司，模糊匹配或精确匹配"
    )
    job_type: Optional[str] = Field(
        default=None,
        description="用工形式：全职/兼职/实习"
    )
    exclude_job_type: list[str] = Field(
        default_factory=list,
        description="排除的用工形式列表，如 ['外包']"
    )
    exclude_company: list[str] = Field(
        default_factory=list,
        description="排除的公司列表"
    )
```

### 字段来源映射

| FilterCriteria 字段 | Slots 字段 | 匹配方式 |
|---------------------|-----------|----------|
| job_title | job_title | 模糊 + Soft Match |
| skills | skills | Soft Match（REQ-005） |
| experience | experience | 数值比较 + 浮动（±20%） |
| education | education | 向上兼容 |
| gender | gender | 精确匹配 |
| city | city | 精确匹配 |
| industry | industry | 模糊匹配 |
| company | company | 模糊/精确 |
| job_type | job_type | 精确匹配 |
| exclude_job_type | exclude (from BR-05) | 排除列表 |

### 学历等级映射

```python
EDUCATION_HIERARCHY = {
    "高中": 1,
    "大专": 2,
    "本科": 3,
    "硕士": 4,
    "博士": 5,
}
```

向上兼容：`candidate.education_level >= filter.education_level`

---

## 模型关系图

```
Slots (from intent-router)
  │
  ├─ 转换 ──> FilterCriteria (REQ-004)
  │
  ├─ 拼接 ──> query_text (REQ-001, REQ-002)
  │
  ▼
RetrievalResult  ◄── Hybrid Retrieval 产出
  │
  ├─ FilterCriteria 过滤 ──> filtered candidates
  │
  ├─ Rerank ──> 更新 metadata.rerank_score
  │
  ├─ WeightConfig + score_breakdown 计算
  │
  ├─ LLM 生成 reason + matched_skills + missing_skills
  │
  ▼
RankingResult  ◄── 最终推荐结果
```

---

## 与外部模块的数据接口

| 数据 | 来源模块 | 说明 |
|------|----------|------|
| Resume 完整数据 | resume-store | 用于 LLM 生成推荐理由（REQ-008） |
| 候选人向量 | vector-index（Milvus） | 用于 Hybrid Retrieval（REQ-001~003） |
| Slots | intent-router | 转化为 query_text + FilterCriteria |
| Skill 标准化映射 | resume-parser | 用于 Soft Match（REQ-005） |
