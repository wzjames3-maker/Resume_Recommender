<!-- Module: vector-index -->
<!-- Spec Layer: 06 - Acceptance -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 06-acceptance: Vector Index

| ID | Given | When | Then |
|----|-------|------|------|
| AC-001 | FlagEmbedding 已加载 | embed_text("Java工程师 5年经验") | 返回 EmbeddingResult(dense[1024], sparse{非空}) |
| AC-002 | 有效 Sparse 向量 | sparse dict | 非空 dict，key 为 int(token_id)，value 为 float(weight > 0) |
| AC-003 | 相同文本重复调用 embed_text | 第二次 | 命中 L1 缓存，不调用 FlagEmbedding |
| AC-004 | L1 缓存过期 | 调用 embed_text | 命中 L2 Redis 缓存，回写 L1 |
| AC-005 | L1 + L2 均未命中 | 调用 embed_text | 调用 FlagEmbedding，回写 L1 + L2 |
| AC-006 | 10 份简历已入库（~150 Chunk） | hybrid_search_small(dense, sparse, top_k=5) | 返回 5 条 Small Chunk 结果，含 chunk_id + resume_id + score |
| AC-007 | hybrid_search_small 返回结果 | 检查 score | score 是 RRF 融合分数（Dense + Sparse 双路贡献） |
| AC-008 | 10 份简历入库 | retrieve_with_parent(top_k=5) | 返回 5 条结果，每条含 small_chunk + parent_chunk |
| AC-009 | Small Chunk 的 parent_chunk_id 存在 | retrieve_with_parent | 返回的 parent_chunk 内容与 parent_chunk_id 对应 |
| AC-010 | Small Chunk 的 parent_chunk_id 不存在 | retrieve_with_parent | 降级返回 Full Resume Chunk |
| AC-011 | resume_id 已删除 | hybrid_search_small | 不返回该简历的任何 Chunk |
| AC-012 | slots.experience=5, slots.education="本科" | build_filter_expr | 返回 `chunk_level == 'small' && years_of_experience >= 5 && highest_education_level >= 2` |
| AC-013 | 过滤表达式传入 hybrid_search_small | 检索结果 | 所有结果满足 years_of_experience >= 5 且 highest_education_level >= 2 |
| AC-014 | 同一 resume_id 的 3 个 Small Chunk 都命中 | 去重 | 只保留最高分的 1 条 |
| AC-015 | 批量写入 15 个 Chunk | insert_chunks | 1 次 flush，全部写入成功 |
| AC-016 | FlagEmbedding 首次调用 | 模型加载 | 耗时 < 120s，后续调用 < 200ms |
| AC-017 | Dense 向量维度 = 1024 | 检查 | dimension == 1024 |
| AC-018 | Sparse 向量 | 检查 | len(sparse) > 0，所有 value > 0 |
