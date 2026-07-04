<!-- Spec: vector-index -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 00-overview: Vector Index

## 来源
PRD §4 FR-002, FR-003; tech-decision.md 决策项 4/5

## 做什么
- 管理 Milvus 向量索引的创建/写入/查询
- 使用 FlagEmbedding 本地推理 BGE-M3 生成 Dense + Sparse 双模态 Embedding
- 支持 Multi-Granularity 向量索引（Small Chunk / Parent Chunk / Full Resume）
- 支持 Hybrid Search（Dense + Sparse 通过 Milvus RRFRanker 真正融合）
- 支持 Small→Big 召回策略
- 支持 Milvus 标量字段预过滤（years_of_experience, highest_education_level, city, gender）
- 入库时从 ResumeStructured 提取标量字段填充，支持向量库级硬约束过滤

## 不做什么
- 不做 Rerank（由 recommendation-engine 负责）
- 不做 Chunk 切分（由 resume-parser 负责）
- 不做简历解析（由 resume-parser 负责）
- 不做 LLM 推荐理由生成（由 recommendation-engine 负责）

## 技术栈

| 组件 | 选型 | 版本 |
|------|------|------|
| 向量数据库 | Milvus Standalone | v2.4.6 (Docker) |
| Python SDK | pymilvus | >=2.4.6,<2.5 |
| Dense Embedding | FlagEmbedding BGEM3FlagModel | BAAI/bge-m3 |
| Sparse Embedding | FlagEmbedding BGEM3FlagModel | BAAI/bge-m3 |
| L1 缓存 | cachetools | >=5.3 |
| L2 缓存 | Redis | >=5.0 |

## 关键设计决策

### D1: FlagEmbedding 本地推理（非 SiliconFlow API）
SiliconFlow `/v1/embeddings` OpenAI Compatible 接口只返回 dense 向量，不暴露 BGE-M3 的 sparse 输出。
因此改用 FlagEmbedding 本地推理，原生支持 dense + sparse + colbert 三模态。
- Dense: 1024d float vector, metric=COSINE
- Sparse: lexical_weights {token_id: weight}, metric=IP
- 模型首次加载 ~2GB（自动从 HuggingFace 下载），后续常驻内存

### D2: 标量字段预过滤
将硬约束字段（years_of_experience, highest_education_level, city, gender）提取为 Milvus 标量列，
在 hybrid_search 的 expr 参数中执行预过滤，而非在 Python 层 post-filter。
- 过滤在向量检索前执行，确保 top_k 结果全部满足硬约束
- 避免检索后过滤导致结果不足

### D3: Small→Big 召回
检索在 Small Chunk 级别执行 Hybrid Search，命中后通过 parent_chunk_id 查询 Parent Chunk 作为 LLM 上下文。
Parent Chunk 不可用时降级使用 Full Resume Chunk。

## Spec 文件索引

| 文件 | 内容 |
|------|------|
| `01-requirements.md` | 13 条 REQ + 6 条 NFR |
| `02-data-model.md` | Milvus Schema + 标量字段映射 + Embedding 数据结构 + 索引定义 |
| `03-api-contract.md` | VectorIndexClient 接口 + EmbeddingGenerator 接口 + 过滤表达式 |
| `04-business-rules.md` | 16 条 RULE（FlagEmbedding 单例 + 双层缓存 + 标量预过滤 + sparse 非空） |
| `05-edge-cases.md` | 16 条 EC（覆盖模型加载、维度验证、降级链路） |
| `06-acceptance.md` | 18 条 AC（Given-When-Then 验收标准） |
| `07-tech-constraints.md` | FlagEmbedding 配置 + 禁用项 + Docker 镜像影响 |
| `08-dependencies.md` | 前置/后置依赖 + 跨模块数据流 |
