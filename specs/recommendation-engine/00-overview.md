<!-- Module: recommendation-engine -->
<!-- Spec Layer: 00 - Overview -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 模块概览：Recommendation Engine（推荐引擎模块）

## 1. 模块定位

Recommendation Engine 是企业智能招聘 RAG 推荐系统的**核心推荐模块**，负责将 HR 的自然语言招聘需求转化为精准的候选人推荐列表。模块串联 Hybrid Retrieval、Rerank、Context Building 和 LLM 推荐理由生成四大环节。

## 2. 来源追溯

| 来源 | 内容 |
|------|------|
| PRD FR-002 | 支持 Hybrid Retrieval（Dense + Sparse） |
| PRD FR-003 | 支持 Metadata Filter（工作年限/学历/城市/性别等硬约束） |
| PRD FR-004 | 支持 LLM Rerank 多维度加权排序（权重可配置） |
| PRD FR-005 | 每条推荐包含 Score / Reason / Matched Skills / Missing Skills / Score Breakdown |
| PRD 附录A | 排序权重默认值：技能 40% + 经验 25% + 项目 20% + 行业 10% + 教育 5% |
| PRD NFR-021~025 | Recall@10 >= 0.85, MRR >= 0.7, NDCG@10 >= 0.75, Faithfulness >= 0.9, Top-10 采纳率 >= 80% |

## 3. 做什么（In Scope）

| 能力 | 说明 |
|------|------|
| Hybrid Retrieval | Dense + Sparse 通过 Milvus RRFRanker 真正融合（非 dense-only） |
| Milvus 标量预过滤 | 硬约束在 Milvus expr 层执行（非 Python post-filter），确保 top_k 全满足 |
| Small→Big 召回 | 检索 Small Chunk，命中后返回 Parent Chunk 作为 LLM 上下文 |
| Resume 级去重 | 同 resume_id 多 chunk 只保留最高分 |
| Weighted Rerank | BGE-Reranker score 与 retrieval score 加权融合（非覆盖式替换） |
| Context Building | 从检索结果构建结构化 LLM 上下文（非 MongoDB N+1 enrichment） |
| LLM 推荐理由 | 使用 LLM 生成自然语言推荐理由（非模板字符串拼接） |
| Score Breakdown | 输出各维度独立评分 |
| 降级策略 | Reranker 不可用时降级到 hybrid_score 排序 |

## 4. 不做什么（Out of Scope）

| 不做 | 负责模块 |
|------|----------|
| Intent 识别 / Slot 提取 | intent-router |
| 简历解析 / Chunk 切分 | resume-parser |
| 向量生成与写入 Milvus | vector-index |
| 对话管理 | conversation-memory |
| API 认证与鉴权 | api-layer |

## 5. 技术栈

| 组件 | 技术选型 | 用途 |
|------|----------|------|
| 向量数据库 | Milvus v2.4.6 (pymilvus >=2.4.6,<2.5) | Hybrid Search + 标量预过滤 |
| Embedding | FlagEmbedding BGEM3FlagModel（本地推理） | 查询向量生成（Dense + Sparse） |
| Reranker | BGE Reranker v2 M3 - SiliconFlow API `/v1/rerank` | 候选精细化重排序 |
| LLM | DeepSeek（主）/ OpenAI（备） | 推荐理由生成 |
| 缓存 | cachetools + Redis | Embedding 缓存 + 推荐理由缓存 |

> **决策注释**: Reranker 保持使用 SiliconFlow 云端 API（`/v1/rerank` 端点独立于 embedding 端点，功能正常可用）。
> 仅 Embedding 从 SiliconFlow API 改为 FlagEmbedding 本地推理（因 `/v1/embeddings` 不返回 sparse 向量）。

## 6. 架构位置（重构后）

```
Slots (from intent-router / LangGraph)
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Hybrid Retrieval (Milvus 标量预过滤)                  │
│   filter_expr = build_filter_expr(slots)                     │
│   → Milvus.hybrid_search_small(dense, sparse, expr)         │
│   → RRF 融合 → list[RetrievalResult]                         │
│   → Resume 级去重（同 resume_id 只保留最高分）                  │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Weighted Rerank                                     │
│   BGE-Reranker API(query, candidates)                       │
│   final_score = α * rerank_score + (1-α) * retrieval_score  │
│   （非覆盖式替换！）                                            │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Context Building                                    │
│   从检索结果构建结构化 LLM 上下文                                │
│   (候选人信息 + 匹配内容 + 招聘需求)                             │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: LLM Reason Generation                               │
│   LLM(context, slots) → reason + matched_skills +           │
│   missing_skills + score_breakdown                          │
│   （真正的 LLM 调用，非模板拼接！）                               │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
          Final Output (list[RankingResult])
```
