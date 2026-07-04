<!-- Module: vector-index -->
<!-- Spec Layer: 08 - Dependencies -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 08-dependencies: Vector Index

## 前置依赖

| 模块 | 依赖内容 |
|------|----------|
| resume-parser | 提供 ChunkSchema 列表（Small + Parent + Full），每个 chunk 含 content + metadata（含标量字段） |

## 后置依赖

| 模块 | 使用方式 |
|------|----------|
| recommendation-engine | 通过 hybrid_search_small + retrieve_with_parent 执行检索 |
| recommendation-engine | 通过 EmbeddingGenerator.generate() 生成查询向量 |
| resume-store | 入库后回写 chunk_ids 列表 |

## 对外接口

```python
from src.vector_index import VectorIndexClient

# 索引管理
client.create_collection()
client.create_indexes()

# 数据写入
client.insert_chunks(chunks: list[ChunkSchema]) -> list[int]
client.delete_chunks_by_resume(resume_id: str) -> None

# 检索
client.hybrid_search_small(query_dense, query_sparse, top_k, expr) -> list[dict]
client.retrieve_with_parent(query_dense, query_sparse, top_k, expr) -> list[dict]

# Embedding
from src.vector_index import get_embedding_generator
generator = get_embedding_generator()
result = generator.generate(text: str) -> EmbeddingResult
results = generator.batch_generate(texts: list[str]) -> list[EmbeddingResult]
```

## 跨模块数据流

```
ResumeParser
  │ (ChunkSchema 列表, metadata 含标量字段)
  v
VectorIndex.insert_chunks()
  │
  ├── 提取标量字段 → Milvus 标量列
  ├── FlagEmbedding generate → dense[1024] + sparse{tok:val}
  └── 写入 Milvus
  │
  v
RecommendationEngine.HybridRetriever
  │ (build_filter_expr → Milvus expr)
  ├── EmbeddingGenerator.generate(query_text) → dense + sparse
  ├── hybrid_search_small(dense, sparse, expr) → RRF 结果
  └── retrieve_with_parent → Small + Parent
```
