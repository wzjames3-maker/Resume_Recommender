<!-- Module: recommendation-engine -->
<!-- Spec Layer: 01 - Requirements -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 功能需求：Recommendation Engine

## 需求总览

| ID | 需求名称 | 优先级 | 来源 |
|----|----------|--------|------|
| REQ-001 | Dense Retrieval | P0 | PRD FR-002 |
| REQ-002 | Sparse Retrieval | P0 | PRD FR-002 |
| REQ-003 | Hybrid Merge | P0 | PRD FR-002, BR-01 |
| REQ-004 | Metadata Filter | P0 | PRD FR-003, BR-02 |
| REQ-005 | Soft Match | P1 | BR-03 |
| REQ-006 | LLM Rerank | P0 | PRD FR-004 |
| REQ-007 | 多维度加权排序 | P0 | PRD FR-004, 附录A |
| REQ-008 | 推荐理由生成 | P0 | PRD FR-005, BR-09 |
| REQ-009 | Score Breakdown | P0 | PRD FR-005 |
| REQ-010 | Deduplication | P1 | BR-10 |
| REQ-011 | 可配置排序权重 | P1 | PRD 附录A |
| REQ-012 | 降级策略 | P0 | PRD NFR-020 |
| REQ-013 | Small→Big 召回 | P0 | 新增 |
| REQ-014 | 多粒度上下文拼装 | P0 | 新增 |

---

## REQ-001: Dense Retrieval

**优先级**: P0
**来源**: PRD FR-002

### 描述

使用 BGE-M3 模型生成查询的 Dense 向量，在 Milvus 中执行 Dense 向量相似度检索（COSINE 距离），返回 Top-K 候选。

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query_text | str | 是 | 由 Slots 拼接的查询文本（如"Java工程师 5年 杭州 985"） |
| top_k | int | 是 | 初始召回数量，默认 50 |

### 输出

- `list[RetrievalResult]`：包含 `resume_id`、`dense_score`、`metadata`

### 行为规则

- 查询文本由 `job_title + skills + 其他关键描述` 拼接而成
- Dense 向量通过 BGE-M3 云端 API 生成，返回 1024 维浮点向量
- 使用 Milvus `search` API，metric_type=`COSINE`，返回 `top_k` 条结果
- Embedding 结果应缓存（cachetools），避免相同查询重复调用 API

### 追溯

- 实现时引用: 04-business-rules.md RULE-001, 07-tech-constraints.md

---

## REQ-002: Sparse Retrieval

**优先级**: P0
**来源**: PRD FR-002

### 描述

使用 BGE-M3 模型生成查询的 Sparse 向量，在 Milvus 中执行 Sparse 向量检索（BM25 风格），返回 Top-K 候选。

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query_text | str | 是 | 查询文本（同 REQ-001） |
| top_k | int | 是 | 初始召回数量，默认 50 |

### 输出

- `list[RetrievalResult]`：包含 `resume_id`、`sparse_score`、`metadata`

### 行为规则

- Sparse 向量与 Dense 向量由 BGE-M3 同一次 API 调用同时生成
- 使用 Milvus Sparse 字段的 `search` API
- Sparse 检索擅长精确关键词匹配（如专有名词、技术术语），作为 Dense 语义检索的补充

### 追溯

- 实现时引用: 04-business-rules.md RULE-001, 07-tech-constraints.md

---

## REQ-003: Hybrid Merge

**优先级**: P0
**来源**: PRD FR-002, BR-01

### 描述

将 Dense Retrieval 和 Sparse Retrieval 的结果通过 Reciprocal Rank Fusion (RRF) 算法合并为统一的候选列表。

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| dense_results | list[RetrievalResult] | 是 | Dense 检索结果 |
| sparse_results | list[RetrievalResult] | 是 | Sparse 检索结果 |
| rrf_k | int | 否 | RRF 常数 k，默认 60 |
| top_k | int | 是 | 合并后保留数量，默认 50 |

### 输出

- `list[RetrievalResult]`：合并后的候选列表，包含 `resume_id`、`dense_score`、`sparse_score`、`hybrid_score`

### 行为规则

- RRF 公式: `score(d) = Σ 1 / (k + rank_i(d))`，其中 `k=60`，`rank_i` 为文档 d 在第 i 个检索器中的排名
- 同一 `resume_id` 在 Dense 和 Sparse 结果中都出现时，RRF 分数叠加
- 仅在 Dense 结果中出现的候选，Sparse 排名视为无穷大（不贡献 Sparse 分数），反之亦然
- 合并后按 `hybrid_score` 降序排列，取 Top-K

### 追溯

- 实现时引用: 04-business-rules.md RULE-001

---

## REQ-004: Metadata Filter

**优先级**: P0
**来源**: PRD FR-003, BR-02

### 描述

在 Hybrid Merge 之后，对候选列表应用硬约束过滤，移除不满足条件的候选人。

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| candidates | list[RetrievalResult] | 是 | 候选列表 |
| filters | FilterCriteria | 是 | 过滤条件（参见 02-data-model.md） |

### 输出

- `list[RetrievalResult]`：通过过滤的候选列表

### 行为规则

- **城市（city）**: 精确匹配或"远程"标记
- **学历（education）**: 向上兼容（要求"硕士"→ 可匹配硕士/博士，不可匹配本科）
- **工作年限（experience）**: 按 `experience_op`（>=, <=, ==, between）进行数值比较
- **性别（gender）**: 精确匹配（需注意法律法规合规性，参见 PRD O-001）
- **期望岗位（job_title）**: 模糊匹配，结合 Soft Match（REQ-005）
- **用工形式（job_type）**: 支持排除列表（如 `exclude_job_type=["外包"]`）
- **行业（industry）**: 模糊匹配
- **公司（company）**: 模糊匹配或精确匹配
- **年龄（age）**: 按范围过滤

### 追溯

- 实现时引用: 04-business-rules.md RULE-002, 05-edge-cases.md EC-001

---

## REQ-005: Soft Match

**优先级**: P1
**来源**: BR-03

### 描述

在 Metadata Filter 中，对技能和年限字段采用软匹配策略，避免过度过滤导致召回率下降。

### 输入

- 同 REQ-004，但 FilterCriteria 中的某些字段采用宽松匹配

### 输出

- 同 REQ-004

### 行为规则

**技能软匹配**:
- "Java工程师" 可召回: Java / Kotlin+Java / Spring Boot / Java+Go
- 维护技能近义词映射表（由 resume-parser 的 Skill 标准化提供）
- 软匹配的技能在 `matched_skills` 中标注匹配方式

**年限浮动**:
- 默认浮动范围 ±20%（可配置）
- 如要求 5 年 → 可召回 4~6 年的候选人
- 超出浮动范围的不通过

**不允许的软匹配**:
- 城市必须精确匹配
- 学历只能向上兼容，不可降级

### 追溯

- 实现时引用: 04-business-rules.md RULE-003

---

## REQ-006: LLM Rerank

**优先级**: P0
**来源**: PRD FR-004

### 描述

使用 BGE Reranker v2 M3 对经过 Metadata Filter 的候选进行精细化重排序，输出相关性分数。

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| candidates | list[RetrievalResult] | 是 | 过滤后的候选列表 |
| query | str | 是 | 原始查询文本 |
| slots | dict | 是 | 解析后的 Slots |

### 输出

- `list[RankingResult]`：包含 `resume_id`、`rerank_score`、`rank`

### 行为规则

- BGE Reranker v2 M3 接受 (query, document) 对，输出 0~1 的相关性分数
- 每个候选人的 document 为其简历摘要（由 resume-store 提供）
- Rerank 分数 `rerank_score` 作为后续多维度加权排序的一个输入信号
- 调用超时阈值：3 秒（参见 05-edge-cases.md EC-002）
- Reranker 不可用时降级（参见 REQ-012）

### 追溯

- 实现时引用: 04-business-rules.md RULE-004, 05-edge-cases.md EC-002

---

## REQ-007: 多维度加权排序

**优先级**: P0
**来源**: PRD FR-004, 附录A

### 描述

基于五个维度的分数加权计算最终排序分数（0-100），支持权重配置。

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| candidates | list | 是 | Rerank 后的候选 |
| slots | dict | 是 | 查询 Slots（用于计算各维度匹配度） |
| weight_config | WeightConfig | 否 | 排序权重配置，默认值参见附录A |

### 输出

- `list[RankingResult]`：包含 `resume_id`、`final_score`（0-100）、`rank`、`score_breakdown`

### 维度定义

| 维度 | 权重（默认） | 计算方式 |
|------|-------------|----------|
| 技能匹配度（skill_match） | 40% | `matched_skills_count / required_skills_count * 100`，加语义相似度修正 |
| 工作经验匹配（experience_match） | 25% | 年限匹配度（考虑浮动）+ 岗位相关性 |
| 项目经历相关性（project_relevance） | 20% | 项目领域 + 技术栈与 Slots 的重叠度 |
| 行业经验（industry_match） | 10% | 候选人行业与目标行业的匹配度 |
| 教育背景（education_match） | 5% | 学历等级 + 学校层级（985/211/双一流） |

### 行为规则

- `final_score = Σ(dimension_score * weight) * 100`，归一化到 0-100
- `score_breakdown` 包含每个维度的独立分数（0-100）
- 权重总和必须为 1.0（参见 05-edge-cases.md EC-007 自动归一化）
- Reranker 分数可作为 `skill_match` 维度的加权信号之一

### 追溯

- 实现时引用: 04-business-rules.md RULE-004, 05-edge-cases.md EC-007

---

## REQ-008: 推荐理由生成（Batch 合并 + Lazy Load 按需加载）

**优先级**: P0
**来源**: PRD FR-005, BR-09

### 描述

使用 LLM 为推荐候选人生成自然语言推荐理由。采用 **Batch 合并策略**（单次 LLM 调用生成 Top-N 全部候选人的理由）和 **Lazy Load 按需加载**（前端展开详情时才触发单个生成），降低 LLM API 调用量和 RPM 压力。

### 策略说明

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| **Batch 合并** | 将 Top-N 候选人的简历摘要 + Score Breakdown 打包到一个 Prompt，LLM 一次返回全部理由 | 默认策略，适用于 Top-5 推荐 |
| **Lazy Load** | 前端卡片默认只展示评分，HR 点击展开详情时才触发单个理由生成 | 前端交互优化，适用于长列表 |
| **模板降级** | LLM 不可用时，基于 Score Breakdown 自动生成模板化理由 | 降级场景 |

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| candidates | list[RankingResult] | 是 | Top-N 排序后的候选列表（不含 reason） |
| query | str | 是 | 原始查询文本 |
| slots | dict | 是 | 查询 Slots |
| mode | Literal["batch", "single"] | 否 | batch=批量生成全部，single=单个按需生成，默认 batch |

### Batch Prompt 设计

将 Top-N（最多 5 人）的简历摘要和 Score Breakdown 打包到单个 Prompt 中，LLM 一次性返回 JSON 格式的全部理由。相比 N 次独立调用，节省 (N-1) 次网络 I/O，RPM 降低 80%。

### 行为规则

- Batch 模式下一次 LLM 调用生成全部候选人的理由（默认 Top-5）
- Single 模式用于 Lazy Load 按需生成单个候选人的理由
- 推荐理由至少 2 条，每条引用简历中的具体信息（Faithfulness 约束）
- Prompt 中明确指示 LLM：推荐理由必须基于简历原文，禁止编造
- 生成后校验 matched_skills 必须是候选人简历中实际存在的技能
- LLM 不可用时降级为模板化理由（参见 REQ-012）
- Batch 结果缓存到 Redis（key=MD5(resume_id+query_hash)，TTL=24h）

### 追溯

- 实现时引用: 04-business-rules.md RULE-005, RULE-006, 05-edge-cases.md EC-003


---

## REQ-009: Score Breakdown

**优先级**: P0
**来源**: PRD FR-005

### 描述

输出每个候选人在五个维度上的独立评分，使 HR 能理解排序逻辑。

### 输入

- 同 REQ-007

### 输出

```python
{
    "skill_match": float,       # 0-100
    "experience_match": float,  # 0-100
    "project_relevance": float, # 0-100
    "industry_match": float,    # 0-100
    "education_match": float    # 0-100
}
```

### 行为规则

- 每个维度分数独立计算，归一化到 0-100
- Score Breakdown 随 `RankingResult` 一起输出
- 分数计算逻辑必须可追溯到具体的数据字段（如 `matched_skills_count`）

### 追溯

- 实现时引用: PRD FR-005, 06-output-contract.md

---

## REQ-010: Deduplication

**优先级**: P1
**来源**: BR-10

### 描述

同一候选人在一次推荐中只能出现一次。

### 输入

- `candidates`: 候选列表（可能包含同一人的多份简历）

### 输出

- 去重后的候选列表

### 行为规则

- 判定同一候选人的维度：`candidate_id`（resume-store 中的唯一标识）
- 同一候选人有多份简历时，取 `resume_id` 最大的（最新版本）
- 去重在 Hybrid Merge 之后、Metadata Filter 之前执行

### 追溯

- 实现时引用: 04-business-rules.md RULE-007, 05-edge-cases.md EC-008

---

## REQ-011: 可配置排序权重

**优先级**: P1
**来源**: PRD 附录A

### 描述

不同岗位可使用不同的排序权重配置。

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| job_title | str | 否 | 岗位名称，用于查找预设权重 |
| weight_config | WeightConfig | 否 | 直接传入权重配置，优先级高于预设 |

### 输出

- `WeightConfig`: 生效的权重配置

### 行为规则

- 默认权重：技能 40% + 经验 25% + 项目 20% + 行业 10% + 教育 5%
- 如传入 `weight_config`，直接使用
- 如传入 `job_title` 且存在预设权重，使用预设权重
- 如均未传入，使用默认权重
- 预设权重存储在配置文件中，支持运行时修改

### 追溯

- 实现时引用: 04-business-rules.md RULE-004

---

## REQ-012: 降级策略

**优先级**: P0
**来源**: PRD NFR-020

### 描述

当外部依赖不可用时，系统必须有降级路径，保证核心推荐链路不中断。

### 降级场景

| 场景 | 降级策略 | 影响 |
|------|----------|------|
| Reranker API 不可用 | 跳过 Rerank，使用 `hybrid_score` 排序 | 排序精度下降，功能可用 |
| LLM 不可用（理由生成） | 使用模板化理由：基于 score_breakdown 自动生成 | 理由质量下降，功能可用 |
| Dense Embedding API 不可用 | 降级到纯 Sparse 检索 | 语义匹配能力下降，关键词匹配可用 |
| Sparse Embedding API 不可用 | 降级到纯 Dense 检索 | 关键词匹配能力下降，语义匹配可用 |
| Milvus 连接超时 | 返回错误码 `RETRIEVAL_TIMEOUT`，不返回结果 | 功能不可用，需人工介入 |

### 行为规则

- 降级时在返回结果中增加 `degradation` 字段，说明降级原因
- 降级事件记录到 Audit Log
- 每种降级场景独立处理，不互相影响
- Milvus 不可用为致命错误，无法降级

### 追溯

- 实现时引用: 04-business-rules.md RULE-009, 05-edge-cases.md EC-002, EC-005, EC-006
---

## REQ-013: Small→Big 召回

**优先级**: P0
**来源**: Chunk Optimization 策略

### 描述

Hybrid Retrieval 在 Small Chunk 级别执行精准检索，命中后通过 parent_chunk_id 查找对应的 Parent Chunk，将 Parent Chunk 作为 LLM 推荐理由生成的上下文。

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| small_chunk_results | list[RetrievalResult] | 是 | Small Chunk 级别的检索结果 |
| vector_client | VectorIndexClient | 是 | 向量索引客户端 |

### 输出

- `list[RetrievalWithContext]`：每个结果包含 `small_chunk`（检索命中）+ `parent_context`（LLM 上下文）

### 行为规则

- 检索在 Small Chunk 级别执行（`chunk_level="small"`）
- 命中 Small Chunk 后，通过 `parent_chunk_id` 查找 Parent Chunk
- 若 `parent_chunk_id` 指向的 Parent Chunk 不存在，降级使用 Full Resume Chunk
- 去重：同一 resume_id 的多个 Small Chunk 命中时，合并为一个候选人，取最高 score
- Parent Context 用于 LLM 推荐理由生成（REQ-008），不用于排序

### 追溯

- 实现时引用: vector-index Spec RULE-007, RULE-008

---

## REQ-015: 推荐理由 Lazy Load 按需生成

**优先级**: P1
**来源**: LLM 配额优化

### 描述

前端候选人卡片默认只展示 Score Breakdown（无需 LLM），HR 点击展开详情时按需调用后端 API 生成单个候选人的推荐理由。先查 Redis 缓存（Batch 可能已缓存），未命中则调 LLM single 模式生成。

### 追溯
- 实现时引用: 04-business-rules.md RULE-005, RULE-006

---

## REQ-014: 多粒度上下文拼装

**优先级**: P0
**来源**: Chunk Optimization 策略

### 描述

将检索命中的 Parent Chunk 拼装为 LLM 推荐理由生成的输入上下文，而不是使用整份简历。

### 输入

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| parent_chunks | list[ParentContext] | 是 | 候选人的 Parent Chunk 列表 |
| full_resume | str | 否 | 候选人完整简历（降级时使用） |

### 输出

- `str`：拼装后的上下文文本

### 行为规则

- 优先使用命中的 Parent Chunk 作为上下文（精准且节省 Token）
- Parent Chunk 按 `sequence_index` 排序，保持简历原有顺序
- 如 Parent Chunk 为空，降级使用 Full Resume
- 上下文总长度限制 4000 Token（超出时截断低优先级的 Parent Chunk）
- 优先保留与查询最相关的 Section 类型（如查询"Java 工程师"，优先保留工作经历和项目经历）
---
## v1.2-data-pipeline 新增 (2026-06-26)
| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-010 | FR-002 | Small→Big 聚合必须调用 VectorIndex.retrieve_with_parent() 获取 parent chunk 真实内容（非仅透传 parent_chunk_id） | P0 |
| REQ-011 | FR-002 | RRF 合并后的去重逻辑使用 resume_id（而非 candidate_name + skills 组合键） | P1 |
