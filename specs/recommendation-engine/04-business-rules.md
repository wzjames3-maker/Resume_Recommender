<!-- Module: recommendation-engine -->
<!-- Spec Layer: 04 - Business Rules -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 业务规则：Recommendation Engine

## 规则总览

| ID | 规则名称 | 优先级 |
|----|----------|--------|
| RULE-001 | Hybrid Retrieval + Milvus 标量预过滤 | P0 |
| RULE-002 | Resume 级去重 | P0 |
| RULE-003 | Weighted Rerank（加权融合，非覆盖） | P0 |
| RULE-004 | Context Builder（结构化 LLM 上下文） | P0 |
| RULE-005 | LLM 推荐理由生成（非模板拼接） | P0 |
| RULE-006 | 多维度 Score Breakdown | P1 |
| RULE-007 | 推荐数量与 top_k | P1 |
| RULE-008 | 降级策略 | P0 |
| RULE-009 | 推荐理由缓存 | P1 |

---

## RULE-001: Hybrid Retrieval + Milvus 标量预过滤

**来源**: PRD FR-002, FR-003

### 规则描述

每次推荐查询执行真正的 Hybrid Search（Dense + Sparse 通过 Milvus RRFRanker 融合），硬约束在 Milvus expr 层预过滤。

### 关键约束

1. **Dense + Sparse 双路检索**: FlagEmbedding 生成查询的 dense[1024] + sparse{tok:val}，两者都传入 Milvus hybrid_search
2. **Milvus 标量预过滤**: 硬约束（years_of_experience, highest_education_level, city, gender）在 Milvus expr 中执行，不在 Python 层 post-filter
3. **检索范围**: 仅在 Small Chunk 级别（`chunk_level == 'small'`）
4. **over-fetch**: top_k 设为 count * 3（给 Rerank 留余量）
5. **Small→Big**: 命中后通过 parent_chunk_id 查询 Parent Chunk 作为上下文

### 过滤表达式构建

```python
def build_filter_expr(slots: CandidateSlot) -> str:
    conditions = ["chunk_level == 'small'"]
    if slots.experience is not None:
        op = ">=" if slots.experience_op != "<=" else "<="
        conditions.append(f"years_of_experience {op} {int(slots.experience)}")
    if slots.education:
        level = EDUCATION_LEVEL_MAP[slots.education.value]  # 本科=2
        conditions.append(f"highest_education_level >= {level}")
    if slots.city:
        conditions.append(f'city == "{slots.city}"')
    if slots.gender:
        conditions.append(f'gender == "{slots.gender}"')
    return " && ".join(conditions)
```

### 查询文本构建

```python
def build_query_text(slots, raw_query) -> str:
    """从 Slots + 原始查询构建检索文本"""
    keywords = []
    if slots.job_title: keywords.append(slots.job_title)
    if slots.skills: keywords.extend(slots.skills)
    if slots.experience is not None: keywords.append(f"{int(slots.experience)}年经验")
    if slots.industry: keywords.append(slots.industry)
    # 包含原始用户查询以保留语义
    if raw_query and raw_query.strip():
        keywords.insert(0, raw_query.strip())
    return " ".join(keywords)
```

---

## RULE-002: Resume 级去重

同一 resume_id 的多个 Small Chunk 命中时，只保留最高分的。

```python
def deduplicate(results: list[RetrievalResult]) -> list[RetrievalResult]:
    seen = {}
    for r in results:
        if r.resume_id not in seen or r.score > seen[r.resume_id].score:
            seen[r.resume_id] = r
    return list(seen.values())
```

去重在 Small→Big 聚合后、Rerank 之前执行。

---

## RULE-003: Weighted Rerank（加权融合，非覆盖）

**来源**: PRD FR-004

### 规则描述

BGE-Reranker 分数与检索分数**加权融合**，不覆盖检索分数。

### 融合公式

```
final_score = RERANK_WEIGHT * rerank_score + RETRIEVAL_WEIGHT * normalized_retrieval_score
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| RERANK_WEIGHT | 0.7 | Reranker 权重 |
| RETRIEVAL_WEIGHT | 0.3 | 检索分数权重 |

### 查询文本构建

Reranker 的 query 不能只用 job_title，应构建完整的招聘需求描述：

```python
def build_rerank_query(slots, raw_query) -> str:
    parts = [f"招聘需求："]
    if slots.job_title: parts.append(f"岗位: {slots.job_title}")
    if slots.experience is not None: parts.append(f"经验: {int(slots.experience)}年以上")
    if slots.education: parts.append(f"学历: {slots.education.value}及以上")
    if slots.city: parts.append(f"城市: {slots.city}")
    if slots.skills: parts.append(f"技能: {', '.join(slots.skills)}")
    return " ".join(parts)
```

### Document 构建

每个候选人的 document 不只是 chunk.content，而是结构化信息：

```python
def build_document(result: RetrievalResult) -> str:
    m = result.metadata
    return f"{m.get('candidate_name','')} | {m.get('current_title','')} | " \
           f"{m.get('years_of_experience',0)}年经验 | " \
           f"技能: {', '.join(m.get('skills_normalized',[]))} | " \
           f"内容: {result.content}"
```

### 降级

Reranker API 不可用 → 跳过 Rerank，直接使用 retrieval_score 排序，标记 `reranker_fallback`。

---

## RULE-004: Context Builder（结构化 LLM 上下文）

**来源**: PRD FR-005

### 规则描述

为 LLM 推荐理由生成构建结构化上下文，包含候选人信息 + 匹配内容 + 招聘需求。

### 上下文结构

```python
class LLMContext:
    candidate_info: str      # 姓名、职位、公司、年限、城市、学历
    matched_content: str      # 检索命中的 Parent Chunk 内容
    candidate_skills: list[str]  # 候选人技能列表
    job_requirements: str     # 招聘需求（岗位、技能、经验、学历、城市）
```

### 构建规则

1. **候选人信息**: 从 chunk.metadata 提取（已在入库时填充，无需 MongoDB 查询）
2. **匹配内容**: 使用 retrieve_with_parent 返回的 Parent Chunk 内容
3. **Token 限制**: 总上下文 <= 4000 tokens（中文 1 字 ≈ 1.5 tokens）
4. **截断策略**: 超限时按 section 相关性截断（experience > project > skill > education）

### 与旧实现对比

| 维度 | 旧实现 | 新实现 |
|------|--------|--------|
| Metadata 来源 | 查询时 MongoDB N+1 enrichment | 入库时已填充到 chunk.metadata |
| 上下文构建 | 无（直接用 chunk.content） | 结构化 LLMContext（候选人+内容+需求） |
| 查询性能 | N+1 MongoDB 查询 | 零额外查询（metadata 已在结果中） |

---

## RULE-005: LLM 推荐理由生成（非模板拼接）

**来源**: PRD FR-005, NFR-024

### 规则描述

使用 LLM 生成自然语言推荐理由，包含 reason、matched_skills、missing_skills、score_breakdown。

**禁止使用模板字符串拼接**（如 `f"{name}，具备 {skills}，拥有 {years} 年经验"`）。

### Prompt 设计

```
基于以下候选人信息和招聘需求，生成推荐理由。

{structured_context}

请输出JSON:
{
  "reason": "2-3句话的推荐理由，说明为什么推荐该候选人",
  "matched_skills": ["匹配的技能"],
  "missing_skills": ["缺失的技能"],
  "score_breakdown": {
    "skill_match": 0.0-1.0,
    "experience_match": 0.0-1.0,
    "education_match": 0.0-1.0,
    "project_relevance": 0.0-1.0,
    "industry_match": 0.0-1.0
  }
}
```

### 降级

LLM 不可用 → 使用模板化理由（标注 `llm_fallback`），但模板理由必须包含 matched_skills 和 missing_skills 的基本计算。

---

## RULE-006: 多维度 Score Breakdown

| 维度 | 默认权重 | 计算方式 |
|------|----------|----------|
| skill_match | 40% | matched_skills / required_skills |
| experience_match | 25% | 年限匹配度 + 岗位相关性 |
| project_relevance | 20% | 项目领域重叠 + 技术栈重叠 |
| industry_match | 10% | 行业相似度 |
| education_match | 5% | 学历等级 + 院校层级 |

权重可配置，不同岗位可有不同预设（`config/weight_presets.yaml`）。

---

## RULE-007: 推荐数量与 top_k

| 参数 | 默认值 | 最小 | 最大 |
|------|--------|------|------|
| count | 10 | 1 | 100 |
| top_k | count * 3 | 20 | 200 |

候选不足时返回实际数量，不报错。

---

## RULE-008: 降级策略

| 故障组件 | 降级策略 | 标识 |
|----------|----------|------|
| Reranker API | 跳过 Rerank，用 retrieval_score 排序 | `reranker_fallback` |
| LLM API (理由生成) | 模板化理由（含基本 skill 计算） | `llm_fallback` |
| FlagEmbedding Dense | 仅 Sparse 检索 | `dense_fallback` |
| FlagEmbedding Sparse | 仅 Dense 检索 | `sparse_fallback` |
| Milvus | 不可降级，返回 RETRIEVAL_TIMEOUT | — |

降级信息写入 `result.metadata.degradation`。

---

## RULE-009: 推荐理由缓存

- **Cache Key**: `recommendation:reason:{MD5(resume_id + query_hash)}`
- **TTL**: 24 小时（Redis）
- **写入时机**: LLM 生成成功后异步写入
- **降级**: Redis 不可用时跳过缓存