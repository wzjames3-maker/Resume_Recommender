<!-- Spec: vector-index (简化模块) -->
<!-- 调研决策: ✅ 直接复用 (Milvus + BGE-M3) -->
<!-- 变更: Tier M - Multi-Granularity Chunk Index -->

# 00-overview: Vector Index

## 来源
PRD §4 FR-002, FR-003; tech-decision.md 决策项 4/5

## 做什么
- 管理 Milvus 向量索引的创建/写入/查询
- 使用 BGE-M3 生成 Dense + Sparse 双模态 Embedding
- 支持 Multi-Granularity 向量索引（Small Chunk / Parent Chunk / Full Resume）
- 支持 Hybrid Search（Dense + Sparse）+ Small→Big 召回策略

## 不做什么
- 不做 Rerank（由 recommendation-engine 负责）
- 不做 Metadata Filter（由 recommendation-engine 负责）
- 不做简历解析（由 resume-parser 负责）
- 不做 Chunk 切分（由 resume-parser 负责）

## 技术栈
- 向量数据库: Milvus Standalone (Docker) / Milvus Lite (开发)
- Python SDK: pymilvus>=2.5
- Embedding: BGE-M3 (云端 API, OpenAI Compatible)
- L1 本地缓存: cachetools (Embedding 热数据，进程内毫秒级读取)
- L2 分布式缓存: Redis (Embedding 结果缓存，跨进程共享，TTL 24 小时)

---

# 01-requirements: Vector Index

| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-001 | FR-002 | 创建 Milvus Collection（Multi-Granularity: small/parent/full 三级） | P0 |
| REQ-002 | FR-002 | 写入 Chunk 向量（Dense 1024d + Sparse + chunk_level + parent_chunk_id） | P0 |
| REQ-003 | FR-002 | Dense 向量检索（在 Small Chunk 级别） | P0 |
| REQ-004 | FR-002 | Sparse 向量检索（在 Small Chunk 级别） | P0 |
| REQ-005 | FR-002 | Hybrid Search（Dense + Sparse RRF 合并） | P0 |
| REQ-006 | FR-002 | Small→Big 召回：检索 Small Chunk，返回 Parent Chunk 作为上下文 | P0 |
| REQ-007 | FR-002 | 删除简历所有 Chunk 向量 | P1 |
| REQ-008 | FR-002 | 更新简历向量（先删后插所有 Chunk） | P1 |
| REQ-009 | - | Embedding 结果缓存（减少 API 调用） | P1 |
| REQ-010 | - | 批量 Embedding（异步并发） | P1 |

---

# 02-data-model: Vector Index

## Milvus Collection Schema

```
Collection: resume_chunks
├── id: INT64 (PK, auto_id)
├── chunk_id: VARCHAR(64) (唯一索引, 格式: {resume_id}:{level}:{index})
├── resume_id: VARCHAR(64) (索引, 关联 MongoDB)
├── chunk_level: VARCHAR(16) (索引, "small"/"parent"/"full")
├── parent_chunk_id: VARCHAR(64) (索引, Small Chunk 的父 Chunk ID, parent/full 级别为空)
├── section_type: VARCHAR(32) (索引, "education"/"experience"/"project"/"skill"/"other")
├── dense_vector: FLOAT_VECTOR(1024)  # BGE-M3 Dense
├── sparse_vector: SPARSE_FLOAT_VECTOR  # BGE-M3 Sparse
├── content: VARCHAR(65535)  # Chunk 文本内容
└── metadata: JSON  # {candidate_name, city, skills, experience, education, sequence_index}
```

## 检索参数
- Dense: metric=COSINE, index=HNSW, ef_construction=256, M=16
- Sparse: metric=IP, index=SPARSE_INVERTED_INDEX
- Hybrid: RRF (Reciprocal Rank Fusion) k=60

## 向量写入策略

| Chunk Level | 写入时机 | 向量用途 |
|-------------|----------|----------|
| small | 简历入库时 | 精准语义检索（Hybrid Search 的检索单元） |
| parent | 简历入库时 | Small→Big 上下文提供（检索命中后返回） |
| full | 简历入库时 | 全局语义匹配 + LLM 推荐理由生成的上下文 |

**写入量估算**（单份简历）:
- 1 个 Full Chunk → 1 个向量
- ~4 个 Parent Chunk → ~4 个向量
- ~10 个 Small Chunk → ~10 个向量
- 合计: ~15 个向量/简历
- 10 万份简历 → ~150 万个向量（Milvus 单机无压力）

---

# 03-api-contract: Vector Index

内部接口：
```
create_collection() -> None
insert_chunks(chunks: list[ChunkSchema]) -> list[int]  # 批量写入 Chunk 向量, 返回 Milvus ID 列表
hybrid_search_small(query_dense: list[float], query_sparse: dict, top_k: int, expr: str | None) -> list[dict]
# Small→Big: 检索 Small Chunk，聚合返回 Parent Chunk
retrieve_with_parent(query_dense: list[float], query_sparse: dict, top_k: int, expr: str | None) -> list[dict]
# 返回结果包含: small_chunk (检索命中) + parent_chunk (上下文) + resume_id
delete_chunks_by_resume(resume_id: str) -> None  # 删除简历的所有 Chunk
embed_text(text: str) -> tuple[list[float], dict]  # (dense, sparse)
batch_embed(texts: list[str]) -> list[tuple[list[float], dict]]
```

---

# 04-business-rules: Vector Index

| ID | 规则 |
|----|------|
| RULE-001 | 一份简历生成多个 Chunk 向量（Small + Parent + Full，约 15 个/简历） |
| RULE-002 | Embedding 双层缓存：L1 cachetools（进程内，TTL 1h）+ L2 Redis（分布式，TTL 24h）；L1 命中直接返回，L1 未命中查 L2，L2 未命中调 API 后回写两层 |
| RULE-003 | 批量入库使用 asyncio 并发调用 BGE-M3 API |
| RULE-004 | Milvus Collection 在系统启动时自动创建（如不存在） |
| RULE-005 | chunk_id 在 Milvus 中建立唯一索引，支持按 resume_id 批量删除/更新 |
| RULE-006 | Hybrid Search 仅在 Small Chunk 级别执行（chunk_level="small"） |
| RULE-007 | Small→Big 召回：检索命中 Small Chunk 后，通过 parent_chunk_id 查找 Parent Chunk 作为 LLM 上下文 |
| RULE-008 | 当 Parent Chunk 不可用时（如数据异常），降级使用 Full Resume Chunk 作为上下文 |

---

# 05-edge-cases: Vector Index

| ID | 场景 | 处理 |
|----|------|------|
| EC-001 | BGE-M3 API 超时 | 重试 2 次，仍失败抛异常 |
| EC-002 | Milvus 连接失败 | 返回错误码 RETRIEVAL_TIMEOUT |
| EC-003 | 向量维度不匹配(非1024) | 拒绝写入，记录错误 |
| EC-004 | chunk_id 不存在于 Milvus | delete_chunks_by_resume 静默成功 |
| EC-005 | 缓存命中率低 | cachetools TTL 设为 1 小时 |
| EC-006 | Small Chunk 数量过多（>100/简历） | 截断到 100 个 Small Chunk，记录警告 |
| EC-007 | parent_chunk_id 指向不存在的 Parent Chunk | 降级使用 Full Resume Chunk |

---

# 06-acceptance: Vector Index

| ID | Given | When | Then |
|----|-------|------|------|
| AC-001 | 有效 Chunk 文本 | embed_text | 返回 (dense[1024], sparse_dict) |
| AC-002 | 10 份简历已入库（~150 个 Chunk） | hybrid_search_small(top_k=5) | 返回 5 条 Small Chunk 结果，含 chunk_id + resume_id + score |
| AC-003 | 相同文本重复调用 embed_text | 第二次 | 命中缓存，不调用 API |
| AC-004 | resume_id 已删除 | hybrid_search_small | 不返回该简历的任何 Chunk |
| AC-005 | BGE-M3 API 不可用 | embed_text | 抛出 EmbeddingError |
| AC-006 | 10 份简历入库 | retrieve_with_parent(top_k=5) | 返回 5 条结果，每条包含 small_chunk + parent_chunk |
| AC-007 | Small Chunk 的 parent_chunk_id 存在 | retrieve_with_parent | 返回的 parent_chunk 内容与 parent_chunk_id 对应的 Chunk 一致 |
| AC-008 | Small Chunk 的 parent_chunk_id 不存在 | retrieve_with_parent | 降级返回 Full Resume Chunk 作为上下文 |

---

# 07-tech-constraints: Vector Index

| 类别 | 选择 | 版本 | 理由 |
|------|------|------|------|
| 向量数据库 | Milvus | Standalone/Docker | 原生 Hybrid Search |
| Python SDK | pymilvus | >=2.5 | 官方 SDK |
| Embedding | BGE-M3 | 云端 API | Dense+Sparse 双模态 |
| L1 本地缓存 | cachetools | >=5.5 | Embedding 热数据，进程内毫秒级读取 |
| L2 分布式缓存 | Redis | redis >= 5.0 | Embedding 结果缓存，跨进程共享，TTL 24 小时 |

禁用：不用 ChromaDB（不支持 Hybrid Search）

---

# 08-dependencies: Vector Index

## 前置
- resume-parser: 提供 ChunkSchema 列表（Small + Parent + Full）

## 后置
- recommendation-engine: 通过 hybrid_search_small + retrieve_with_parent 执行检索
- resume-store: 入库后回写 chunk_ids 列表

## 对外接口
- `from src.vector_index import VectorIndexClient`
