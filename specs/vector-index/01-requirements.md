<!-- Module: vector-index -->
<!-- Spec Layer: 01 - Requirements -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 01-requirements: Vector Index

## 来源
PRD §4 FR-002 (Hybrid Retrieval), FR-003 (Metadata Filter)

## 功能需求

| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-001 | FR-002 | 创建 Milvus Collection（含标量字段 + Dense + Sparse 向量字段 + 标量索引） | P0 |
| REQ-002 | FR-002 | 写入 Chunk 向量（Dense 1024d + Sparse lexical_weights + 标量字段 + metadata JSON） | P0 |
| REQ-003 | FR-002 | Dense 向量检索（HNSW + COSINE，在 Small Chunk 级别） | P0 |
| REQ-004 | FR-002 | Sparse 向量检索（SPARSE_INVERTED_INDEX + IP，在 Small Chunk 级别） | P0 |
| REQ-005 | FR-002 | Hybrid Search（Dense + Sparse 通过 Milvus RRFRanker k=60 真正融合） | P0 |
| REQ-006 | FR-002 | Small→Big 召回：检索 Small Chunk，返回 Parent Chunk 作为上下文 | P0 |
| REQ-007 | FR-003 | Milvus 标量字段预过滤（years_of_experience, highest_education_level, city, gender） | P0 |
| REQ-008 | FR-002 | 删除简历所有 Chunk 向量 | P1 |
| REQ-009 | FR-002 | 更新简历向量（先删后插所有 Chunk） | P1 |
| REQ-010 | - | Embedding 双层缓存（L1 cachetools TTL 1h + L2 Redis TTL 24h） | P1 |
| REQ-011 | - | 批量 Embedding（FlagEmbedding batch encode） | P1 |
| REQ-012 | - | Embedding 模型懒加载 + 单例（避免重复加载 ~2GB 模型） | P0 |
| REQ-013 | - | Resume 级去重（同 resume_id 多 chunk 只保留最高分） | P0 |

## 非功能需求

| ID | 需求 | 指标 |
|----|------|------|
| NFR-001 | 单条 Embedding 延迟 | P95 <= 200ms（FlagEmbedding CPU 推理） |
| NFR-002 | 批量 Embedding 吞吐 | >= 50 条/s（batch_size=32） |
| NFR-003 | Hybrid Search 延迟 | P95 <= 100ms（Milvus ANN） |
| NFR-004 | 模型内存占用 | <= 4GB（BGEM3FlagModel fp32） |
| NFR-005 | 模型首次加载时间 | <= 60s（含 HuggingFace 下载，后续 < 10s 热加载） |
| NFR-006 | 标量过滤对 ANN 性能影响 | <= 20% 延迟增加（Milvus expr 过滤） |
