<!-- Module: recommendation-engine -->
<!-- Spec Layer: 02 - Data Model -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 数据模型：Recommendation Engine

## 模型总览

本模块定义 2 个核心 Pydantic Schema，均为内部数据结构，不直接持久化到数据库。过滤条件通过 Milvus expr 执行（非 Python post-filter），权重配置在 RULE-006 中定义。

```
┌─────────────────┐     ┌─────────────────┐
│  RetrievalResult │────>│  RankingResult   │
│  (检索阶段产出)   │     │  (最终推荐产出)   │
└─────────────────┘     └─────────────────┘
```

---

## 1. RetrievalResult

**用途**: Hybrid Retrieval 阶段产出的候选结果，包含 Milvus RRF 融合后的单一分数。

> **变更 (Tier L)**: RRF 融合从 Python 端移至 Milvus 服务端执行。不再有独立的 `dense_score`/`sparse_score` 字段，改用 Milvus RRF 返回的单一 `score`。

```python
class RetrievalResult(BaseModel):
    """检索阶段的候选结果"""

    resume_id: str = Field(..., description="简历唯一标识")
    chunk_id: str = Field(..., description="命中的 Small Chunk ID")
    parent_chunk_id: str | None = Field(None, description="对应 Parent Chunk ID")
    score: float = Field(..., description="Milvus RRF 融合分数 (k=60)")

    content: str = Field(..., description="Chunk 文本内容")
    section_type: str = Field("", description="education/experience/project/skill/other")

    metadata: dict = Field(
        default_factory=dict,
        description="候选人级 + Chunk 级 metadata（入库时填充，含标量字段）"
    )
```

### 生命周期（Tier L）

```
Milvus.hybrid_search_small(dense, sparse, expr)
  → 返回 [RetrievalResult {resume_id, chunk_id, score, content, metadata}]
  → Retrieve with parent_chunk_id
  → Resume 级去重（RULE-002: 同 resume_id 取最高 score）
  → Weighted Rerank（RULE-003: final_score = 0.7 * rerank + 0.3 * norm_score）
  → 填充 RetrievalResult.metadata.rerank_score
```

### 字段说明

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
RetrievalResult ──(去重 + Rerank + Context + LLM)──> RankingResult
```

一个 `RetrievalResult` 经过 Resume 级去重 → Weighted Rerank → Context Build → LLM Reason 后，转化为一个 `RankingResult`。
过滤在 Milvus expr 预过滤阶段完成，不在该流程中体现。

---

---

## 3. WeightConfig（权重配置）

> 权重在 RULE-006 中定义并可通过 `config/weight_presets.yaml` 配置。
> 此模型用于 LLM Score Breakdown 计算，非 Milvus expr 过滤。

```python
class WeightConfig(BaseModel):
    skill_weight: float = 0.40
    experience_weight: float = 0.25
    project_weight: float = 0.20
    industry_weight: float = 0.10
    education_weight: float = 0.05
```

---

## 4. 过滤（Milvus expr，非 Python post-filter）

> **变更 (Tier L)**: 硬约束过滤不在 Python 层执行。`FilterCriteria` Pydantic model 已废弃。
> 过滤通过 Milvus expr 字符串在检索时执行（见 `build_filter_expr()` in 04-business-rules RULE-001）。

支持的标量过滤字段: `years_of_experience`, `highest_education_level`, `city`, `gender`（从 Milvus 标量列读取）。

---

## 模型关系图（Tier L）

```
Slots (from intent-router)
  │
  ├─ build_filter_expr(slots) → Milvus expr 字符串
  ├─ build_query_text(slots, raw_query) → query 文本
  ├─ FlagEmbedding.generate(query_text) → dense[1024] + sparse{tok:val}
  │
  ▼
RetrievalResult  ◄── Milvus.hybrid_search_small(dense, sparse, expr) → RRF score
  │
  ├─ retrieve_with_parent → 填充 parent_chunk content
  ├─ Resume 级去重 (RULE-002)
  ├─ Weighted Rerank (RULE-003): final_score = 0.7*rerank + 0.3*retrieval
  ├─ Context Building (RULE-004)
  ├─ LLM Reason Generation (RULE-005)
  │
  ▼
RankingResult  ◄── 最终推荐结果
```

## 与外部模块的数据接口

| 数据 | 来源 | 说明 |
|------|------|------|
| Chunk metadata（含标量字段） | 入库时填充到 Milvus | 无需运行时 MongoDB 查询 |
| 候选人向量 | vector-index（Milvus） | Hybrid Search |
| Slots | intent-router | → query_text + Milvus expr |
| Embedding | FlagEmbedding BGEM3FlagModel | 本地推理 Dense + Sparse |
