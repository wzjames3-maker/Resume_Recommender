# PIP-T07: Small→Big 聚合: 切换为 retrieve_with_parent + 修去重

## 基本信息
- **对应 Spec**: REC REQ-010, REC RULE-007/008
- **依赖**: PIP-T01
- **预计工时**: 0.5 天
- **优先级**: P0

## 问题

### 问题 1: 假的 Small→Big
`hybrid_retriever._aggregate_with_parent()` (line 216-249) 只是从检索结果读 `parent_chunk_id` 存进 metadata，**从不向 Milvus 查询 parent chunk 的真实内容**。返回的 `content` 始终是 small chunk（50-200 字）。

真正实现 Small→Big 的 `VectorIndex.retrieve_with_parent()` (line 299-383) 已存在但**零生产调用**。

### 问题 2: 去重键脆弱
`workflow.py:179`:
```python
mongo_id = r.metadata.get("candidate_name", "") + str(r.metadata.get("skills", []))
```
同名同技能列表的两个人会被误并。正确做法是用 MongoDB 的 `resume_id` 去重，而非名字+技能组合键。

## 实现要求

### 1. 替换 _aggregate_with_parent
在 `hybrid_retriever.retrieve()` 中:
```python
# 旧: 调用 _dense_search + _sparse_search + rrf_merger + _aggregate_with_parent
# 新: 直接调用 vector_index.retrieve_with_parent()
dense_emb = embedding.dense
sparse_emb = embedding.sparse
raw_results = self.vector_index.retrieve_with_parent(
    query_dense=dense_emb,
    query_sparse=sparse_emb,
    top_k=top_k,
    expr=filter_expr,
)
final_results = self._build_retrieval_results(raw_results)
```

### 2. 修复去重逻辑
在 `workflow.py:175-184`，移除名字+技能键去重:
```python
# 旧: 
seen_mongo_ids = set()
for r in reranked_results:
    mongo_id = r.metadata.get("candidate_name", "") + str(r.metadata.get("skills", []))
    if mongo_id in seen_mongo_ids: continue
    seen_mongo_ids.add(mongo_id)
    final_deduped.append(r)

# 新:
seen_ids = set()
for r in reranked_results:
    if r.resume_id in seen_ids: continue
    seen_ids.add(r.resume_id)
    final_deduped.append(r)
```

### 3. 增加 parent_chunk 内容到返回结果
在搜索结果中增加 `parent_content` 字段供 LLM 推荐理由生成使用。

## 验收检查点
- [ ] `hybrid_retriever.retrieve()` 调用 `vector_index.retrieve_with_parent()`
- [ ] 返回结果包含 parent chunk 的完整内容（非 small chunk）
- [ ] 去重用 `resume_id` 而非名字+技能组合键
- [ ] `rg "_aggregate_with_parent" src/recommendation_engine/` 确认已被移除或重构

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
