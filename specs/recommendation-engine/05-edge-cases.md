<!-- Module: recommendation-engine -->
<!-- Spec Layer: 05 - Edge Cases -->
<!-- ⚠️ 部分更新: BGE-M3/FlagEmbedding 引用已修正，降级链仍为旧架构，待 Tier L 全文重构 -->

# 边界情况与异常处理：Recommendation Engine

## 边界情况总览

| ID | 场景 | 严重度 | 处理策略 |
|----|------|--------|----------|
| EC-001 | 全部候选人不满足硬约束 | 高 | 放宽约束重试 |
| EC-002 | Reranker API 超时 | 高 | 降级到 hybrid_score |
| EC-003 | LLM 理由包含不存在的信息 | 中 | 强制引用原文 + 校验 |
| EC-004 | 候选人数量不足 count | 低 | 返回实际数量 + 提示 |
| EC-005 | 查询向量生成失败 | 高 | 降级到纯 Sparse 检索 |
| EC-006 | Milvus 连接超时 | 致命 | 返回错误码 RETRIEVAL_TIMEOUT |
| EC-007 | 权重配置总和不为 1 | 低 | 自动归一化 |
| EC-008 | 重复简历（同一人多份） | 低 | 取最新 resume_id |
| EC-010 | parent_chunk_id 指向不存在的 Chunk | 数据异常 | Small→Big 召回 | 降级使用 Full Resume Chunk |
| EC-011 | 候选人无任何 Small Chunk 命中 | 检索异常 | Hybrid Retrieval | 不返回该候选人 |

---

## EC-001: 全部候选人都不满足硬约束

**严重度**: 高
**触发条件**: `apply_filters` 后候选列表为空
**关联规则**: RULE-002

### 场景描述

HR 设置了过于严格的过滤条件（如"杭州 + 硕士 + 10年Java + 女性"），导致 Hybrid Retrieval 召回的所有候选人都被 Metadata Filter 排除。

### 处理策略

**分级放宽重试**:

```
Level 0: 原始条件过滤
    ↓ 结果为空
Level 1: 放宽经验浮动（±20% → ±40%）
    ↓ 结果为空
Level 2: 放宽城市（允许"接受远程"的候选人）
    ↓ 结果为空
Level 3: 放宽学历（硕士 → 本科）
    ↓ 结果为空
Level 4: 移除所有软约束，只保留硬约束中的排除条件
    ↓ 结果为空
返回空结果 + 提示: "未找到符合条件的候选人，已逐步放宽以下条件: ..."
```

### 放宽顺序与优先级

| 优先级 | 放宽操作 | 放宽幅度 | 可跳过 |
|--------|----------|----------|--------|
| 1 | 经验浮动 | ±20% → ±40% | 是 |
| 2 | 城市 | 精确 → 允许远程 | 是 |
| 3 | 学历 | 向下兼容一级 | 是 |
| 4 | 行业 | 精确 → 模糊 | 是 |
| 5 | 性别 | 移除该条件 | 是 |

### 实现要点

```python
async def apply_filters_with_retry(
    candidates: list[RetrievalResult],
    filters: FilterCriteria,
) -> FilterResult:
    """分级放宽重试"""
    relaxed = []

    # Level 0: 原始条件
    result = do_apply_filters(candidates, filters)
    if result.filtered:
        return result

    # Level 1: 放宽经验浮动
    if filters.experience is not None:
        original_tolerance = filters.experience_tolerance
        filters.experience_tolerance = 0.40
        result = do_apply_filters(candidates, filters)
        if result.filtered:
            relaxed.append("经验浮动放宽至±40%")
            return FilterResult(filtered=result.filtered, relaxed_filters=relaxed)
        filters.experience_tolerance = original_tolerance

    # Level 2~5: 逐级放宽...

    # 全部放宽后仍为空
    return FilterResult(
        filtered=[],
        relaxed_filters=["已放宽所有条件，仍未找到候选人"],
        removed_count=len(candidates),
    )
```

### 输出要求

- `relaxed_filters` 字段列出所有被放宽的条件
- API Layer 将放宽信息展示给 HR："已放宽以下条件：经验浮动从±20%调整为±40%"

---

## EC-002: Reranker API 超时

**严重度**: 高
**触发条件**: BGE Reranker v2 M3 API 调用超过 3 秒或返回错误
**关联规则**: RULE-009

### 场景描述

云端 Reranker API 响应缓慢或不可用，导致 Rerank 步骤超时。

### 处理策略

1. **超时阈值**: 3 秒（可配置）
2. **重试**: 失败后重试 1 次，间隔 500ms
3. **降级**: 重试仍失败 → 跳过 Rerank，使用 `hybrid_score` 作为排序依据
4. **记录**: 降级事件记录到 Audit Log
5. **标记**: `SearchCandidatesResult.degradation = "reranker_fallback"`

### 实现要点

```python
async def rerank_with_fallback(
    candidates: list[RetrievalResult],
    query: str,
    slots: dict,
    timeout: float = 3.0,
    max_retries: int = 1,
) -> RerankResult:
    for attempt in range(max_retries + 1):
        try:
            result = await asyncio.wait_for(
                call_reranker_api(query, candidates),
                timeout=timeout,
            )
            return RerankResult(ranked=result, degradation=None)
        except (TimeoutError, APIError) as e:
            if attempt < max_retries:
                await asyncio.sleep(0.5)
                continue
            # 降级
            logger.warning(f"Reranker 降级: {e}")
            candidates.sort(key=lambda c: c.hybrid_score, reverse=True)
            return RerankResult(ranked=candidates, degradation="reranker_fallback")
```

### 降级后的影响

- 排序精度可能下降（hybrid_score 不如 Reranker 精细）
- 功能完全可用，不影响其他流程
- 建议在 UI 上提示"本次结果使用基础排序算法"

---

## EC-003: LLM 理由包含简历中不存在的信息

**严重度**: 中
**触发条件**: LLM 生成的推荐理由中包含候选人简历中没有的信息
**关联规则**: RULE-006

### 场景描述

LLM 在生成推荐理由时"幻觉"（hallucination），编造了候选人不具备的技能、经历或成就。

### 处理策略

**预防措施**:
1. Prompt 中明确约束"必须基于简历原文"
2. 使用 Structured Output 约束输出格式
3. Prompt 中包含完整简历文本，减少 LLM 推断空间

**后置校验**:
1. 校验 `matched_skills` 中的每个技能在候选人简历中存在
2. 校验理由中提到的公司名、项目名在简历中存在（关键词匹配）
3. 校验失败 → 标记该条理由为不可信

**处理方式**:
- 单条理由校验失败 → 移除该条理由，补充模板化理由
- 所有理由都校验失败 → 降级为完全模板化理由（`degradation = "llm_faithfulness_fallback"`）

### 实现要点

```python
def validate_and_fix_reasons(
    reason_result: ReasonResult,
    candidate: Resume,
    slots: dict,
) -> ReasonResult:
    """校验并修正推荐理由"""
    valid_reasons = []
    resume_text = candidate.to_text().lower()

    for r in reason_result.reason:
        # 简单校验：理由中的关键技能/公司名在简历中存在
        if is_reason_faithful(r, resume_text):
            valid_reasons.append(r)

    # 理由不足 2 条 → 补充模板化理由
    if len(valid_reasons) < 2:
        template_reasons = generate_template_reasons(candidate, slots, reason_result.score_breakdown)
        needed = 2 - len(valid_reasons)
        valid_reasons.extend(template_reasons[:needed])
        reason_result.degradation = "llm_faithfulness_fallback"

    reason_result.reason = valid_reasons[:5]  # 最多 5 条

    # 校验 matched_skills
    candidate_skills = {s.name.lower() for s in candidate.skills}
    reason_result.matched_skills = [
        s for s in reason_result.matched_skills
        if s.lower() in candidate_skills
    ]

    return reason_result
```

---

## EC-004: 候选人数量不足 count

**严重度**: 低
**触发条件**: 过滤后的候选人数量 < `count` 参数
**关联规则**: RULE-008

### 场景描述

HR 要求推荐 20 人，但满足条件的只有 8 人。

### 处理策略

1. 返回实际找到的 8 人
2. `total_candidates = 8`
3. 不报错
4. API Layer 可在响应中附加提示："符合条件的候选人共 8 人"

### 实现要点

```python
def handle_insufficient_candidates(
    candidates: list[RankingResult],
    requested_count: int,
) -> SearchCandidatesResult:
    """处理候选人不足的情况"""
    return SearchCandidatesResult(
        recommendations=candidates,  # 返回全部
        total_candidates=len(candidates),
        # API Layer 负责附加提示
        degradation=None,  # 不是降级，是正常情况
    )
```

---

## EC-005: 查询向量生成失败

**严重度**: 高
**触发条件**: FlagEmbedding 本地推理失败（网络错误、API 错误、超时等）
**关联规则**: RULE-009

### 场景描述

FlagEmbedding 不可用，无法生成查询的 Dense 和 Sparse 向量。

### 处理策略

**分级降级**:

```
FlagEmbedding 推理
    ↓ 失败
检查本地缓存（cachetools）
    ↓ 未命中
尝试 Dense-only API（如备用 Embedding 服务）
    ↓ 失败
尝试 Sparse-only（使用 BM25 本地实现或 jieba 分词 + 简单 TF-IDF）
    ↓ 失败
返回错误: LLM_ERROR
```

### 实现要点

```python
async def query_encode_with_fallback(query: str) -> EncodeResult:
    """查询编码，带降级"""
    # 1. 检查缓存
    cache_key = f"embed:{hash(query)}"
    if cache_key in embedding_cache:
        cached = embedding_cache[cache_key]
        return EncodeResult(dense=cached[0], sparse=cached[1], degradation=None)

    # 2. 调用 FlagEmbedding 本地推理
    try:
        result = await call_flagembedding(query)
        embedding_cache[cache_key] = (result.dense, result.sparse)
        return EncodeResult(dense=result.dense, sparse=result.sparse, degradation=None)
    except Exception as e:
        logger.error(f"FlagEmbedding 推理失败: {e}")

    # 3. 降级到纯 Sparse（本地 jieba 分词 + TF-IDF）
    try:
        sparse = local_tfidf_encode(query)
        return EncodeResult(dense=None, sparse=sparse, degradation="dense_fallback")
    except Exception as e:
        logger.error(f"本地 Sparse 编码失败: {e}")

    # 4. 完全失败
    raise RetrievalError("RETRIEVAL_TIMEOUT", "查询向量生成失败")
```

### 注意

- 降级到纯 Sparse 时，`RetrievalResult.dense_score` 为 None
- RRF 合并时只使用 Sparse 排名
- `degradation = "dense_fallback"`

---

## EC-006: Milvus 连接超时

**严重度**: 致命
**触发条件**: Milvus 连接超时或连接池耗尽
**关联规则**: RULE-009

### 场景描述

Milvus Standalone 服务不可用（宕机、网络不通、连接池耗尽）。

### 处理策略

**不可降级** — 没有 Milvus 就无法检索候选人。

1. **超时阈值**: 连接超时 5 秒，查询超时 10 秒
2. **重试**: 重试 2 次，间隔 1 秒
3. **全部失败**: 返回错误码 `RETRIEVAL_TIMEOUT`
4. **记录**: 致命错误记录到 Audit Log 和系统日志
5. **告警**: 触发系统告警（如有监控系统集成）

### 实现要点

```python
async def milvus_search_with_retry(
    collection: Collection,
    search_params: dict,
    max_retries: int = 2,
    timeout: float = 10.0,
) -> list[dict]:
    """Milvus 检索，带重试"""
    for attempt in range(max_retries + 1):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(collection.search, **search_params),
                timeout=timeout,
            )
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"Milvus 检索重试 ({attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(1.0)
                continue
            logger.error(f"Milvus 检索最终失败: {e}")
            raise RetrievalError("RETRIEVAL_TIMEOUT", f"Milvus 连接超时: {e}")
```

### 错误响应

```python
class RetrievalError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code  # "RETRIEVAL_TIMEOUT"
        self.message = message
```

---

## EC-007: 权重配置总和不为 1

**严重度**: 低
**触发条件**: 传入的 WeightConfig 五个权重之和 ≠ 1.0
**关联规则**: RULE-004

### 场景描述

HR 或系统配置了不规范的权重（如技能 0.5 + 经验 0.3 + 项目 0.3 + 行业 0.1 + 教育 0.1 = 1.3）。

### 处理策略

**自动归一化**（已在 WeightConfig Pydantic model 中实现）:

```python
@model_validator(mode="after")
def normalize_weights(self) -> "WeightConfig":
    total = (
        self.skill_weight
        + self.experience_weight
        + self.project_weight
        + self.industry_weight
        + self.education_weight
    )
    if abs(total - 1.0) > 0.001:
        logger.info(f"权重总和 {total} ≠ 1.0，自动归一化")
        self.skill_weight /= total
        self.experience_weight /= total
        self.project_weight /= total
        self.industry_weight /= total
        self.education_weight /= total
    return self
```

### 注意

- 归一化是静默操作，不需要告知用户
- 在 Audit Log 中记录归一化前后的权重值

---

## EC-008: 重复简历（同一人多份）

**严重度**: 低
**触发条件**: 同一 `candidate_id` 对应多个 `resume_id`
**关联规则**: RULE-007

### 场景描述

候选人张三先后上传了 3 份简历（2024 版、2025 版、2026 版），vector-index 中有 3 条记录。

### 处理策略

1. **去重时机**: Hybrid Merge 之后、Metadata Filter 之前
2. **去重策略**: 同一 `candidate_id` 保留 `hybrid_score` 最高的（通常对应最新版本）
3. **降级策略**: 如 `candidate_id` 缺失（数据不完整），使用简历中的姓名+手机号去重

### 实现要点

```python
def deduplicate(candidates: list[RetrievalResult]) -> list[RetrievalResult]:
    """去重：同一候选人保留最佳结果"""
    seen: dict[str, RetrievalResult] = {}
    for c in candidates:
        key = c.candidate_id or f"{c.metadata.get('name', '')}:{c.metadata.get('phone', '')}"
        if not key.strip():
            # 无法去重，保留
            seen[f"unknown:{c.resume_id}"] = c
            continue
        if key not in seen or c.hybrid_score > seen[key].hybrid_score:
            seen[key] = c
    return list(seen.values())
```

### 去重后统计

- `total_candidates` 反映去重后的数量
- API Layer 的 `total_candidates` 字段 = 去重后通过 Filter 的数量

### EC-010: parent_chunk_id 指向不存在的 Chunk

**触发条件**: Small Chunk 的 parent_chunk_id 在 Milvus 中找不到对应的 Parent Chunk

**处理策略**:
```
1. 记录警告日志: "parent_chunk_id {id} not found, falling back to full resume"
2. 使用该 resume_id 的 Full Resume Chunk 作为上下文
3. 在 SearchCandidatesResult.degradation 中标记 "parent_chunk_fallback"
```

### EC-011: 候选人无任何 Small Chunk 命中

**触发条件**: 某个 resume_id 的所有 Small Chunk 在检索中均未命中

**处理策略**:
```
1. 该候选人不出现在检索结果中（不参与后续排序）
2. 不做额处理（正常现象，检索相关性不足）
```
