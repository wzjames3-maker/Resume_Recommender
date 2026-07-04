<!-- Module: vector-index -->
<!-- Spec Layer: 03 - API Contract -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 03-api-contract: Vector Index

## 内部接口

```python
from src.vector_index import VectorIndexClient
```

---

## 1. create_collection() -> None

创建 Milvus Collection（幂等，已存在则跳过）。

创建后自动创建所有索引（dense HNSW + sparse + 标量索引）。

**异常**: `ExternalServiceError(VEC_002)`

---

## 2. insert_chunks(chunks: list[ChunkSchema]) -> list[int]

批量写入 Chunk 向量到 Milvus。

**输入**:
- `chunks`: ChunkSchema 列表，每个包含:
  - chunk_id, resume_id, chunk_level, parent_chunk_id, section_type
  - content (文本)
  - metadata (JSON，含标量字段)

**处理流程**:
1. 从 chunk.metadata 提取标量字段 (years_of_experience, highest_education_level, city, gender)
2. 调用 EmbeddingGenerator.batch_generate(chunks[].content) 获取 dense + sparse
3. 组装 Milvus 写入数据（标量字段 + 向量字段 + content + metadata JSON）
4. 分批写入（每批 MAX_BATCH_SIZE=500）
5. 统一 flush（不再每批 flush）

**输出**: Milvus auto_id 列表

**异常**: `ExternalServiceError(VEC_002)`

---

## 3. hybrid_search_small(query_dense, query_sparse, top_k, expr) -> list[dict]

Small Chunk 级别 Hybrid Search。

**输入**:
- `query_dense: list[float]` — 查询 Dense 向量 [1024]
- `query_sparse: dict[int, float]` — 查询 Sparse 向量 {token_id: weight}
- `top_k: int` — 返回数量
- `expr: str | None` — Milvus 标量过滤表达式

**处理流程**:
1. 构建 Dense AnnSearchRequest (anns_field=dense_vector, metric=COSINE, ef=128)
2. 构建 Sparse AnnSearchRequest (anns_field=sparse_vector, metric=IP)
3. **两个 request 都传入** hybrid_search（真正的双路检索）
4. RRFRanker(k=60) 融合排序
5. 输出 chunk_id, resume_id, chunk_level, parent_chunk_id, section_type, content, metadata, score

**输出**: list[dict]，每条含 chunk 信息 + score

**关键约束**: query_sparse **不能为空**（必须是 FlagEmbedding 生成的真实 sparse 向量）

**异常**: `ExternalServiceError(VEC_001)`

---

## 4. retrieve_with_parent(query_dense, query_sparse, top_k, expr) -> list[dict]

Small→Big 召回：检索 Small Chunk，返回 Parent Chunk 作为上下文。

**处理流程**:
1. 调用 hybrid_search_small 获取 top_k Small Chunk
2. 提取唯一 parent_chunk_id 列表
3. Milvus query 获取 Parent Chunk 内容
4. 组装结果: {small_chunk, parent_chunk, resume_id, section_type, score}
5. Parent Chunk 不存在时降级使用 Full Resume Chunk

**输出**: list[dict]

**异常**: `ExternalServiceError(VEC_001)`

---

## 5. delete_chunks_by_resume(resume_id: str) -> None

按 resume_id 删除所有 Chunk。

**异常**: `ExternalServiceError(VEC_002)`

---

## 6. EmbeddingGenerator 接口

### 6.1 generate(text: str) -> EmbeddingResult

生成单条文本的 Dense + Sparse Embedding。

**处理流程**:
1. 检查 L1 缓存 (cachetools, TTL 1h)
2. L1 未命中 → 检查 L2 缓存 (Redis, TTL 24h)
3. L2 未命中 → 调用 FlagEmbedding BGEM3FlagModel.encode()
4. 回写 L1 + L2 缓存
5. 返回 EmbeddingResult(dense[1024], sparse{tok:val})

**关键约束**:
- FlagEmbedding 模型懒加载 + 单例（首次调用时加载，后续复用）
- use_fp16=False（CPU 模式，兼容无 GPU 环境）

### 6.2 batch_generate(texts: list[str]) -> list[EmbeddingResult]

批量生成 Embedding。

**处理流程**:
1. 检查缓存，分离 uncached
2. uncached 文本分批调用 FlagEmbedding（batch_size=32）
3. 回写缓存
4. 返回完整结果列表

---

## 7. 过滤表达式构建（跨模块参考）

> **注意**: 此方法由 recommendation-engine.HybridRetriever 实现，非 vector-index。
> 列于此文件作为接口契约参考 —— 本模块确保 Milvus 标量列可供此表达式查询。

```python
def build_filter_expr(slots: CandidateSlot) -> str:
    conditions = ["chunk_level == 'small'"]
    
    if slots.experience is not None:
        op = ">=" if slots.experience_op != "<=" else "<="
        conditions.append(f"years_of_experience {op} {int(slots.experience)}")
    
    if slots.education:
        level = EDUCATION_LEVEL_MAP[slots.education.value]  # "本科" -> 2
        conditions.append(f"highest_education_level >= {level}")
    
    if slots.city:
        conditions.append(f'city == "{slots.city}"')
    
    if slots.gender:
        conditions.append(f'gender == "{slots.gender}"')
    
    return " && ".join(conditions)
```

**示例输出**:
```
chunk_level == 'small' && years_of_experience >= 5 && highest_education_level >= 2 && city == "杭州"
```
