<!-- Module: recommendation-engine -->
<!-- Spec Layer: 04 - Business Rules -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 业务规则：Recommendation Engine

## 规则总览

| ID | 规则名称 | 来源 | 优先级 |
|----|----------|------|--------|
| RULE-001 | Hybrid Retrieval 执行策略 | BR-01 | P0 |
| RULE-002 | Metadata Filter 硬约束 | BR-02 | P0 |
| RULE-003 | Soft Match 软匹配 | BR-03 | P1 |
| RULE-004 | 多维度加权排序 | BR-04, 附录A | P0 |
| RULE-005 | 推荐结果完整性 | BR-09, FR-005 | P0 |
| RULE-006 | 推荐理由 Faithfulness | BR-09 | P0 |
| RULE-007 | 去重规则 | BR-10 | P1 |
| RULE-008 | 推荐数量 | BR-08 | P1 |
| RULE-009 | 降级策略 | NFR-020 | P0 |
| RULE-010 | Small→Big 上下文聚合 | REQ-013 | P0 |
| RULE-011 | 推荐理由上下文拼装 | REQ-014 | P0 |
| RULE-012 | 推荐理由缓存 | - | P1 |

---

## RULE-001: Hybrid Retrieval 执行策略

**来源**: PRD FR-002, BR-01

### 规则描述

每次推荐查询必须同时执行 Dense Retrieval 和 Sparse Retrieval，然后通过 RRF（Reciprocal Rank Fusion）合并结果。

### 执行细节

1. **并行执行**: Dense 和 Sparse 检索应并行发起（asyncio.gather），减少总延迟
2. **RRF 合并公式**: `score(d) = Σ 1/(k + rank_i(d))`，其中 `k=60`
3. **RRF 常数 k**: 默认 60，可通过配置调整（取值范围 30~120）
4. **初始召回量 top_k**: 默认 50，即 Dense 和 Sparse 各取 Top-50 Small Chunk，合并后保留 Top-50
5. **查询文本构建**: 由 `job_title + skills + 关键描述` 拼接，去停用词
6. **检索范围**: 仅在 Small Chunk 级别执行（Milvus filter: `chunk_level = "small"`）
7. **Small→Big**: 检索命中 Small Chunk 后，通过 parent_chunk_id 聚合为 Parent Chunk 上下文

### 查询文本构建规则

```python
def build_query_text(slots: dict) -> str:
    """
    从 Slots 构建查询文本。

    优先级：job_title > skills > experience > 其他
    拼接示例：
    - {"job_title": "Java工程师", "skills": ["Java", "Spring Boot"], "experience": 5}
      → "Java工程师 Java Spring Boot 5年经验"
    """
    parts = []
    if slots.get("job_title"):
        parts.append(slots["job_title"])
    if slots.get("skills"):
        parts.extend(slots["skills"])
    if slots.get("experience"):
        parts.append(f"{slots['experience']}年经验")
    if slots.get("industry"):
        parts.append(slots["industry"])
    query_text = " ".join(parts).strip()
    if not query_text:
        raise InvalidQueryError(
            code="EMPTY_QUERY",
            message="查询文本为空：所有 Slot 字段均未提供有效值",
        )
    return query_text
```

### 空查询防御

- **规则**: 当 `build_query_text()` 返回结果为空时，必须抛出 `InvalidQueryError`（错误码 `EMPTY_QUERY`），**严禁向 Milvus 发起无条件空查询**
- **原因**: 空向量查询会导致 Milvus 近似全表扫描，造成极高延迟和资源浪费
- **防御层级**: 意图识别层（intent-router）为主要拦截层，检索层为最终兜底
- **错误码**: `EMPTY_QUERY`，上游调用方应返回友好提示（如"请输入招聘需求"）

### 约束

- Dense 和 Sparse 检索都不应单独使用，必须合并后输出
- 即使某一检索降级，另一检索的结果仍需作为 `RetrievalResult` 输出
- 检索仅在 Small Chunk 级别执行，不在 Parent/Full 级别执行
- Small Chunk 命中后必须聚合为 Parent Chunk，同一 resume_id 的多个 Small Chunk 合并为一个候选人

---

## RULE-002: Metadata Filter 硬约束

**来源**: PRD FR-003, BR-02

### 规则描述

对结构化条件进行硬过滤，不满足条件的候选人直接排除。硬约束是 **AND** 关系（所有条件必须同时满足）。

### 各字段过滤规则

| 字段 | 匹配方式 | 规则 | 例外 |
|------|----------|------|------|
| city | 精确匹配 | 候选人期望城市 == 要求城市 | "远程" 标记可匹配任何城市 |
| education | 向上兼容 | 候选学历等级 >= 要求学历等级 | 不可降级（硕士要求不可匹配本科） |
| experience | 数值比较 + 浮动 | 按 experience_op 比较，浮动 ±20% | 浮动范围可配置 |
| gender | 精确匹配 | 候选性别 == 要求性别 | 可选字段，不填则不过滤 |
| job_type | 精确匹配 | 候选用工形式 == 要求用工形式 | - |
| exclude_job_type | 排除列表 | 候选用工形式 NOT IN 排除列表 | - |
| exclude_company | 排除列表 | 候选公司 NOT IN 排除列表 | - |
| age | 范围过滤 | age_min <= 候选年龄 <= age_max | - |
| industry | 模糊匹配 | 候选行业包含或语义匹配要求行业 | - |
| company | 模糊/精确 | 候选公司包含或等于要求公司 | - |

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

### 经验浮动计算

```python
EXPERIENCE_TOLERANCE = 0.20  # ±20%，可配置

def experience_in_range(
    candidate_exp: float,
    required_exp: float,
    op: str,
    tolerance: float = EXPERIENCE_TOLERANCE,
) -> bool:
    """
    经验浮动匹配。

    示例：要求 5 年，tolerance=0.20
    - >=5: 可匹配 4.0~∞（5 * (1-0.2) = 4.0）
    - <=5: 可匹配 0~6.0（5 * (1+0.2) = 6.0）
    - ==5: 可匹配 4.0~6.0
    - between 3-5: 可匹配 2.4~6.0
    """
```

### 执行顺序

1. 先执行无依赖的字段过滤（city, education, gender, job_type, exclude_*）
2. 再执行需要 metadata 查询的字段（experience, age, industry, company）
3. 短路求值：一旦某条件不满足，立即排除，不再检查后续条件

---

## RULE-003: Soft Match 软匹配

**来源**: BR-03

### 规则描述

在 Metadata Filter 中，部分字段允许软匹配（近似匹配），避免过度过滤。

### 技能软匹配

| 匹配类型 | 说明 | 示例 |
|----------|------|------|
| 精确匹配 | 技能名完全一致 | "Java" == "Java" |
| 近义词匹配 | 通过技能标准化词典映射 | "Java工程师" → ["Java", "Spring Boot"] |
| 包含匹配 | 候选人技能包含要求技能 | 候选人有 "Java+Spring Boot"，要求 "Java" → 匹配 |
| 语义匹配 | 语义相近的技能 | "后端开发" ≈ "Java"（由 LLM 或词典判定） |

**不允许的软匹配**:
- "Java" 不可匹配 "Python"（不同技术栈）
- "React" 不可匹配 "Vue"（不同框架，即使都是前端）

### 年限浮动

- 默认浮动范围: ±20%（`EXPERIENCE_TOLERANCE = 0.20`）
- 浮动后仍不满足 → 排除
- 浮动范围可通过配置调整

### 学历匹配

- **只能向上兼容**，不可降级
- "要求本科" → 可匹配: 本科、硕士、博士
- "要求硕士" → 可匹配: 硕士、博士，不可匹配: 本科

### 城市匹配

- **精确匹配**，不允许模糊匹配
- 例外: 候选人标记"接受远程" → 可匹配任何城市

### 软匹配结果标注

软匹配的技能在输出中需标注匹配方式:

```python
matched_skills = [
    {"name": "Java", "match_type": "exact"},
    {"name": "Spring Boot", "match_type": "synonym", "matched_from": "Java工程师"},
]
```

---

## RULE-004: 多维度加权排序

**来源**: PRD FR-004, 附录A

### 规则描述

最终排序由五个维度的加权分数决定，权重可配置。

### 默认权重

| 维度 | 权重 | 计算公式 |
|------|------|----------|
| skill_match | 40% | matched_skills / required_skills * 100 |
| experience_match | 25% | 年限匹配度 * 0.5 + 岗位相关性 * 0.5 |
| project_relevance | 20% | project_domain_overlap * 0.6 + tech_stack_overlap * 0.4 |
| industry_match | 10% | industry_similarity * 100 |
| education_match | 5% | education_level_score * 0.5 + school_tier_score * 0.5 |

### 加权计算

```python
def calculate_final_score(
    score_breakdown: ScoreBreakdown,
    weight_config: WeightConfig,
) -> float:
    """加权计算最终分数，归一化到 0-100"""
    final = (
        score_breakdown.skill_match * weight_config.skill_weight
        + score_breakdown.experience_match * weight_config.experience_weight
        + score_breakdown.project_relevance * weight_config.project_weight
        + score_breakdown.industry_match * weight_config.industry_weight
        + score_breakdown.education_match * weight_config.education_weight
    )
    return round(final, 1)  # 保留 1 位小数
```

### 岗位预设权重

不同岗位可有不同的权重配置，通过 `config/weight_presets.yaml` 配置:

| 岗位 | 技能 | 经验 | 项目 | 行业 | 教育 |
|------|------|------|------|------|------|
| 默认 | 40% | 25% | 20% | 10% | 5% |
| 算法工程师 | 30% | 20% | 20% | 10% | 20% |
| 产品经理 | 25% | 30% | 25% | 15% | 5% |
| 架构师 | 35% | 30% | 25% | 5% | 5% |

---

## RULE-005: 推荐结果完整性

**来源**: PRD FR-005, BR-09

### 规则描述

每条推荐结果必须包含以下所有字段，缺失任何一个视为无效。

### 必填字段清单

| 字段 | 类型 | 最低要求 |
|------|------|----------|
| score | float | 0-100，保留 1 位小数 |
| reason | list[str] | 至少 2 条，每条 10-200 字 |
| matched_skills | list[str] | 可为空列表，但必须存在 |
| missing_skills | list[str] | 可为空列表，但必须存在 |
| score_breakdown | dict | 5 个维度，每个 0-100 |
| matched_experience | str | 可为 None，但建议填写 |

### 校验逻辑

```python
def validate_ranking_result(result: RankingResult) -> bool:
    """校验推荐结果完整性"""
    assert len(result.reason) >= 2, "推荐理由不足 2 条"
    assert 0 <= result.final_score <= 100, "分数超出范围"
    assert result.score_breakdown is not None, "缺少 score_breakdown"
    # score_breakdown 的 5 个维度都在 0-100
    for dim in ["skill_match", "experience_match", "project_relevance",
                "industry_match", "education_match"]:
        val = getattr(result.score_breakdown, dim)
        assert 0 <= val <= 100, f"{dim} 超出范围: {val}"
    return True
```


### Batch 合并约束（REQ-008 更新）

- **默认 Batch 模式**: Top-N（最多 5 人）的理由在一次 LLM 调用中生成，禁止 N 次独立调用
- **Lazy Load**: 前端展开详情时按需生成单个理由，先查 Redis 缓存再调 LLM
- **理由缓存**: Batch 和 Single 结果均缓存到 Redis（key=MD5(resume_id+query_hash)，TTL=24h）
- **Batch Prompt 校验**: LLM 返回 JSON 必须包含全部候选人理由；部分缺失时对缺失候选人单独重试 1 次
- **RPM 保护**: 结合 Redis 令牌桶限流器，Batch 模式下 RPM 降低 80%
---

## RULE-006: 推荐理由 Faithfulness

**来源**: BR-09

### 规则描述

推荐理由必须基于候选人简历中的真实信息，禁止 LLM 编造或推测不存在的内容。

### 约束

1. **Prompt 约束**: LLM Prompt 中明确指示「必须引用简历原文」
2. **后置校验**: 生成后校验 `matched_skills` 中的技能在候选人简历中确实存在
3. **后置校验**: 生成后校验理由中提到的公司名、项目名在简历中存在
4. **降级**: 校验失败时，使用模板化理由替换（参见 REQ-012）

### 校验策略

```python
def validate_reason_faithfulness(
    reason: list[str],
    matched_skills: list[str],
    candidate: Resume,
) -> bool:
    """
    校验推荐理由的 Faithfulness。

    检查项:
    1. matched_skills 中的每个技能在 candidate.skills 中存在
    2. 理由文本中提到的关键实体（公司、项目、技能）在简历中存在
    """
    # 检查 matched_skills
    candidate_skill_names = {s.name for s in candidate.skills}
    for skill in matched_skills:
        if skill not in candidate_skill_names:
            return False  # 匹配了简历中不存在的技能

    # 检查理由中的关键实体（简单版本：关键词匹配）
    resume_text = candidate.to_text()  # 简历全文
    for r in reason:
        # 提取理由中的关键名词（可用 LLM 或简单 NLP）
        # 简单策略：检查是否有明确的实体引用
        pass

    return True
```

---

## RULE-007: 去重规则

**来源**: BR-10

### 规则描述

同一候选人在一次推荐中只能出现一次。

### 判定逻辑

1. **同一候选人**: `candidate_id` 相同（resume-store 中的唯一标识）
2. **多份简历**: 同一候选人有多份简历（如更新过版本），取 `resume_id` 最大的（最新版本）
3. **去重时机**: Hybrid Merge 之后、Metadata Filter 之前

### 实现

```python
def deduplicate(candidates: list[RetrievalResult]) -> list[RetrievalResult]:
    """
    去重：同一 candidate_id 只保留最新 resume_id。

    去重策略：保留 hybrid_score 最高的那份简历（通常是最新版本）。
    """
    seen: dict[str, RetrievalResult] = {}
    for c in candidates:
        cid = c.candidate_id
        if cid not in seen or c.hybrid_score > seen[cid].hybrid_score:
            seen[cid] = c
    return list(seen.values())
```

### 注意

- 去重后候选数量可能减少，不影响 `count` 参数（count 是最大返回数）
- 去重后 `total_candidates` 应反映去重后的数量

---

## RULE-008: 推荐数量

**来源**: BR-08

### 规则描述

推荐数量有默认值和上下界限制。

### 规则

| 参数 | 默认值 | 最小值 | 最大值 |
|------|--------|--------|--------|
| count | 10 | 1 | 100 |
| top_k | 50 | 20 | 200 |

### 处理逻辑

```python
def validate_count(count: int) -> int:
    """校验和修正推荐数量"""
    if count < 1:
        return 1
    if count > 100:
        return 100
    return count

def validate_top_k(top_k: int, count: int) -> int:
    """top_k 必须 >= count"""
    return max(top_k, count, 20)  # 至少召回 20
```

### 候选不足时的处理

- 如过滤后候选人数 < count，返回实际数量
- 在响应中增加 `total_candidates` 字段告知实际数量
- 不报错，不重试

---

## RULE-009: 降级策略

**来源**: PRD NFR-020

### 规则描述

外部依赖不可用时，系统必须有降级路径，保证核心推荐链路不中断。

### 降级矩阵

| 故障组件 | 降级策略 | 性能影响 | 功能影响 | 标识 |
|----------|----------|----------|----------|------|
| BGE Reranker API 超时/错误 | 跳过 Rerank，使用 hybrid_score 排序 | 延迟减少 3s | 排序精度下降 | `reranker_fallback` |
| LLM API 超时/错误（理由生成） | 使用模板化理由 | 延迟减少 5s | 理由质量下降 | `llm_fallback` |
| Dense Embedding API 失败 | 降级到纯 Sparse 检索 | 延迟减少 0.5s | 语义匹配能力下降 | `dense_fallback` |
| Sparse Embedding API 失败 | 降级到纯 Dense 检索 | 延迟减少 0.5s | 关键词匹配能力下降 | `sparse_fallback` |
| BGE-M3 API 完全失败 | 尝试使用本地缓存的 Embedding | - | 可能返回陈旧结果 | `embedding_cache_fallback` |
| Milvus 连接超时/错误 | 返回错误码 RETRIEVAL_TIMEOUT | - | 功能不可用 | 不可降级 |

### 降级链路

```
正常链路: Dense + Sparse → RRF → Filter → Rerank → Score + Reason
                                                          │
降级场景 1 (Reranker down):                                │
  Dense + Sparse → RRF → Filter → hybrid_score排序 → Score + Template Reason
                                                          │
降级场景 2 (LLM down):                                     │
  Dense + Sparse → RRF → Filter → Rerank → Score + Template Reason
                                                          │
降级场景 3 (Dense down):                                   │
  Sparse only → Filter → Rerank → Score + Reason
                                                          │
降级场景 4 (Sparse down):                                  │
  Dense only → Filter → Rerank → Score + Reason
```

### 降级通知

- 降级信息写入 `SearchCandidatesResult.degradation` 字段
- 降级事件记录到 Audit Log（包含错误详情和时间戳）
- API Layer 可选择将降级信息展示给用户（如"排序精度可能降低"）

---

## RULE-010: Small→Big 上下文聚合

**来源**: Chunk Optimization 策略

### 规则描述

Hybrid Retrieval 在 Small Chunk 级别执行，命中后聚合为 Parent Chunk 作为 LLM 上下文。

### 聚合逻辑

```
输入: small_chunk_results (检索命中的 Small Chunk 列表)

1. 按 resume_id 分组:
   - group_by(resume_id) → {resume_id: [small_chunk_1, small_chunk_2, ...]}

2. 每个 resume_id 取最高 score:
   - hybrid_score = max(small_chunk.hybrid_score for small_chunk in group)

3. 查找 Parent Chunk:
   - 对每个命中的 Small Chunk，取 parent_chunk_id
   - 去重 parent_chunk_id（同一 Parent 可能被多个 Small Chunk 引用）
   - 通过 vector_index 查找 Parent Chunk 的 content
   - IF Parent Chunk 不存在 → 降级使用 Full Resume Chunk

4. 输出:
   - RetrievalWithContext {
       resume_id,
       hybrid_score (组内最高),
       parent_chunks: [ParentChunk_1, ParentChunk_2, ...],
       matched_small_chunks: [SmallChunk_1, SmallChunk_2, ...]
     }
```

### 示例

```
查询: "Java 5年 杭州"

检索命中 (Small Chunk 级别):
  - r_001:small:0003 score=0.92 "2022.07-至今 阿里巴巴 高级Java工程师"
  - r_001:small:0004 score=0.89 "负责订单系统核心模块开发"
  - r_001:small:0007 score=0.85 "精通 Java, Spring Boot, MySQL"
  - r_002:small:0012 score=0.88 "Java 后端开发 4年经验"

聚合后:
  - r_001: score=0.92, parent_chunks=[工作经历 Parent, 技能清单 Parent]
  - r_002: score=0.88, parent_chunks=[工作经历 Parent]
```

---

## RULE-011: 推荐理由上下文拼装

**来源**: Chunk Optimization 策略

### 规则描述

LLM 生成推荐理由时，使用命中的 Parent Chunk 作为上下文，而不是整份简历。

### 拼装策略

```
输入: candidate_parent_chunks (候选人的 Parent Chunk 列表)

1. 排序: 按 sequence_index 排序（保持简历原有顺序）

2. 截断:
   - 计算总 Token 数（粗算: 中文 1 字 ≈ 1.5 Token）
   - IF 总 Token > 4000:
       按相关性截断（与查询相关的 Section 类型优先保留）
       相关性排序: experience > project > skill > education > other

3. 拼装:
   ```
   === 候选人: {candidate_name} ===

   [工作经历]
   {parent_chunk_experience.content}

   [项目经历]
   {parent_chunk_project.content}

   [技能清单]
   {parent_chunk_skill.content}
   ```

4. 降级:
   - IF parent_chunks 为空 → 使用 full_resume（截断到 4000 Token）
```

### Token 限制

| 上下文来源 | Token 上限 | 说明 |
|------------|-----------|------|
| Parent Chunk 拼装 | 4000 | 优先策略 |
| Full Resume | 4000 | 降级策略 |

---

## RULE-012: 推荐理由缓存

**来源**: 性能优化

### 规则描述

相同候选人 + 相同查询条件的推荐理由缓存到 Redis，其他 HR 搜同样条件时直接命中缓存，减少 LLM 调用。

### 缓存策略

1. **Cache Key**: ecommendation:reason:{MD5(resume_id + query_hash)}
2. **query_hash**: 对排序后的查询条件 JSON 字典计算 MD5，保证相同条件生成相同 hash
3. **TTL**: 24 小时
4. **写入时机**: LLM 生成推荐理由成功后，异步写入 Redis
5. **读取时机**: 推荐理由生成前，优先查询 Redis 缓存
6. **缓存未命中**: 调用 LLM 生成理由，成功后回写 Redis
7. **降级**: Redis 不可用时跳过缓存，直接调用 LLM（不阻塞主链路）

### Cache Key 构建

`python
import hashlib
import json

def build_reason_cache_key(resume_id: str, query_slots: dict) -> str:
    """
    构建推荐理由缓存 Key。
    - resume_id: 候选人简历 ID
    - query_slots: 查询条件（排序后序列化保证一致性）
    """
    query_str = json.dumps(query_slots, sort_keys=True, ensure_ascii=False)
    query_hash = hashlib.md5(query_str.encode()).hexdigest()
    return f"recommendation:reason:{resume_id}:{query_hash}"
`

### 约束

- 缓存的是 LLM 生成的推荐理由文本（str），不是整个推荐结果
- 推荐理由依赖 LLM 模型版本，模型切换时需清空缓存（通过 key 前缀批量删除）
- 缓存写入必须异步执行，不阻塞推荐结果返回