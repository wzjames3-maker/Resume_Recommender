<!-- Module: recommendation-engine -->
<!-- Spec Layer: 00 - Overview -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 模块概览：Recommendation Engine（推荐引擎模块）

## 1. 模块定位

Recommendation Engine 是企业智能招聘 RAG 推荐系统的**核心推荐模块**，负责将 HR 的自然语言招聘需求转化为精准的候选人推荐列表。模块串联 Hybrid Retrieval、Metadata Filter、LLM Rerank 和推荐理由生成四大环节，为上游 API Layer 提供端到端的推荐能力。

## 2. 来源追溯

| 来源 | 内容 |
|------|------|
| PRD FR-002 | 支持 Hybrid Retrieval（Dense + Sparse） |
| PRD FR-003 | 支持 Metadata Filter（工作年限/学历/城市/性别等硬约束） |
| PRD FR-004 | 支持 LLM Rerank 多维度加权排序（权重可配置） |
| PRD FR-005 | 每条推荐包含 Score / Reason / Matched Skills / Missing Skills / Score Breakdown |
| PRD 附录A | 排序权重默认值：技能 40% + 经验 25% + 项目 20% + 行业 10% + 教育 5% |
| 05-business-rules.md | BR-01 Hybrid Retrieval, BR-02 Metadata Filter, BR-03 Soft Match, BR-04 多维度加权排序, BR-08 推荐数量, BR-09 可解释性, BR-10 去重 |
| 06-output-contract.md | recruitment.search 响应结构定义 |
| PRD NFR-021~025 | Recall@10 >= 0.85, MRR >= 0.7, NDCG@10 >= 0.75, Faithfulness >= 0.9, Top-10 采纳率 >= 80% |

## 3. 做什么（In Scope）

| 能力 | 说明 |
|------|------|
| Dense Retrieval | 使用 BGE-M3 Dense 向量进行语义相似度检索（Milvus） |
| Sparse Retrieval | 使用 BGE-M3 Sparse 向量进行关键词检索（Milvus） |
| Hybrid Merge | 将 Dense + Sparse 结果通过 RRF（Reciprocal Rank Fusion）合并 |
| Metadata Filter | 对硬约束字段（城市/学历/年限/性别等）进行后过滤 |
| Soft Match | 允许相近技能（Java ≈ Spring Boot）和年限浮动（±20%） |
| LLM Rerank | 使用 BGE Reranker v2 M3 对候选进行精细化重排序 |
| 多维度加权排序 | 按技能/经验/项目/行业/教育五个维度加权计算最终分数 |
| 推荐理由生成 | 使用 LLM（DeepSeek/OpenAI）生成自然语言推荐理由 |
| Score Breakdown | 输出各维度的独立评分，支持 HR 理解排序逻辑 |
| Deduplication | 同一候选人多份简历时去重，取最新版本 |
| 降级策略 | Reranker 不可用时降级到 hybrid_score 排序 |
| Small→Big 召回 | 检索 Small Chunk（单句级），命中后返回 Parent Chunk（Section 级）作为 LLM 上下文 |
| 多粒度上下文拼装 | 将检索命中的 Parent Chunk 拼装为 LLM 推荐理由生成的输入上下文 |

## 4. 不做什么（Out of Scope）

| 不做 | 说明 | 负责模块 |
|------|------|----------|
| Intent 识别 | 不负责理解 HR 的自然语言意图 | intent-router |
| Slot 提取 | 不负责从自然语言中提取结构化参数 | intent-router |
| 简历解析 | 不负责将 PDF/DOCX 解析为结构化数据 | resume-parser |
| 简历持久化 | 不负责简历的 CRUD 存储 | resume-store |
| 向量生成与写入 | 不负责简历 Embedding 生成和 Milvus 写入 | vector-index |
| 对话管理 | 不负责多轮对话状态和历史管理 | conversation-memory |
| 候选人详情展示 | 不负责完整简历的组装和 PII 脱敏 | api-layer |
| API 认证与鉴权 | 不负责 JWT 和 RBAC | api-layer |

## 5. 技术栈

| 组件 | 技术选型 | 版本要求 | 用途 |
|------|----------|----------|------|
| 向量数据库 | Milvus Standalone | pymilvus >= 2.5 | Dense + Sparse 混合检索 |
| Embedding 模型 | BGE-M3（云端 API） | OpenAI Compatible API | 查询向量生成（Dense + Sparse） |
| Reranker 模型 | BGE Reranker v2 M3（云端 API） | 专用 API | 候选精细化重排序 |
| LLM | DeepSeek（主）/ OpenAI（备） | OpenAI Compatible API | 推荐理由生成 |
| 缓存 | cachetools | cachetools >= 5.5 | Embedding 结果缓存 |
| 缓存 | Redis | redis >= 5.0 | 推荐理由缓存（候选人+查询条件 → 理由，TTL 24h） |
| 数据验证 | Pydantic | Pydantic >= 2.0 | Schema 定义与输出约束 |
| HTTP 客户端 | httpx | httpx >= 0.28 | 调用云端 API |

## 6. 架构位置

```
┌──────────────┐     ┌───────────────────────┐     ┌──────────────┐
│ Intent Router │────>│  Recommendation Engine │────>│   API Layer   │
│ (Slots)       │     │  (本模块)              │     │  (FastAPI)    │
└──────────────┘     │                       │     └──────────────┘
                     │  ┌─────────────────┐  │
                     │  │ 1. Query Encode  │  │     ┌──────────────┐
                     │  │    BGE-M3 API    │  │────>│  Vector Index │
                     │  └────┬────────────┘  │     │  (Milvus)     │
                     │       │               │     └──────────────┘
                     │  ┌────▼────────────┐  │
                     │  │ 2. Hybrid       │  │
                     │  │    Retrieval     │  │
                     │  │    Dense+Sparse  │  │
                     │  └────┬────────────┘  │
                     │       │               │
                     │  ┌────▼────────────┐  │
                     │  │ 3. Metadata     │  │     ┌──────────────┐
                     │  │    Filter        │  │────>│ Resume Store  │
                     │  └────┬────────────┘  │     │  (MongoDB)    │
                     │       │               │     └──────────────┘
                     │  ┌────▼────────────┐  │
                     │  │ 4. LLM Rerank   │  │     ┌──────────────┐
                     │  │    BGE Reranker  │  │────>│ Reranker API  │
                     │  └────┬────────────┘  │     └──────────────┘
                     │       │               │
                     │  ┌────▼────────────┐  │
                     │  │ 5. Score Calc   │  │
                     │  │    + Reason Gen  │  │     ┌──────────────┐
                     │  └────┬────────────┘  │────>│   LLM API     │
                     │       │               │     │ DeepSeek/OpenAI│
                     │  ┌────▼────────────┐  │     └──────────────┘
                     │  │ 6. Output       │  │
                     │  │    Assembly      │  │
                     │  └─────────────────┘  │
                     └───────────────────────┘
```

## 7. 数据流

```
Slots (from intent-router)
  │
  ├─ query_text ──> BGE-M3 API ──> dense_vector + sparse_vector
  │
  ├─ filters (city/education/experience/...) ──> FilterCriteria
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Hybrid Retrieval (Small Chunk 级别)                    │
│   Milvus.search(dense_vector, sparse_vector, top_k,           │
│     filter="chunk_level='small'")                              │
│   → RRF Merge → list[RetrievalResult]                         │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 1.5: Small→Big 上下文聚合                                │
│   对每个命中的 Small Chunk:                                    │
│     - 通过 parent_chunk_id 查找 Parent Chunk                   │
│     - 若 Parent Chunk 不存在 → 降级使用 Full Resume Chunk      │
│   → list[RetrievalResult + parent_context]                    │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│ Step 2: Metadata Filter                              │
│   apply_filters(candidates, FilterCriteria)          │
│   → 硬约束过滤 + Soft Match                          │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│ Step 3: LLM Rerank                                   │
│   BGE Reranker(query, candidates)                    │
│   → 精细化重排序                                      │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│ Step 4: Score Calculation + Reason Generation        │
│   score_breakdown = weighted_sum(dimensions)         │
│   reason = LLM(query, candidate_resume, slots)       │
│   → list[RankingResult]                              │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
         Final Output (list[RankingResult])
```

## 8. 关键约束

1. **引用 Spec 条目** — 所有实现必须追溯到本 Spec 的 REQ/RULE/AC 编号
2. **容器内执行** — 所有测试和运行在 Docker 容器内
3. **降级优先** — 任何外部依赖（Reranker/LLM/Embedding）不可用时，必须有降级路径，保证核心链路可用
4. **Faithfulness** — 推荐理由必须引用简历原文片段，禁止 LLM 捏造信息
5. **权重可配置** — 排序权重不硬编码，支持运行时配置和按岗位定制
6. **内部接口** — 不对外暴露，仅供 API Layer 通过函数调用使用
7. **串行门控** — 一次只执行一个任务，过检查点才进下一个

## 9. Spec 文件索引

| 文件 | 内容 | 层级 |
|------|------|------|
| `00-overview.md` | 模块概览（本文件） | 概览 |
| `01-requirements.md` | 功能需求列表 | 需求 |
| `02-data-model.md` | 数据模型与 Schema 定义 | 模型 |
| `03-api-contract.md` | 内部接口契约 | 接口 |
| `04-business-rules.md` | 业务规则 | 规则 |
| `05-edge-cases.md` | 边界情况与异常处理 | 边界 |
| `06-acceptance.md` | 验收标准（Given-When-Then） | 验收 |
| `07-tech-constraints.md` | 技术约束与依赖版本 | 约束 |
| `08-dependencies.md` | 模块依赖关系 | 依赖 |
