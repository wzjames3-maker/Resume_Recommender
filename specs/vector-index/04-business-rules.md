<!-- Module: vector-index -->
<!-- Spec Layer: 04 - Business Rules -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 04-business-rules: Vector Index

| ID | 规则 |
|----|------|
| RULE-001 | 一份简历生成 ~15 个 Chunk 向量（1 Full + ~5 Parent + ~10 Small），每个生成 Dense + Sparse 双向量 |
| RULE-002 | Embedding 使用 FlagEmbedding 本地推理（BGEM3FlagModel），不使用 SiliconFlow API |
| RULE-003 | FlagEmbedding 模型懒加载 + 单例模式：首次调用 encode() 时加载 ~2GB 模型到内存，后续复用 |
| RULE-004 | Embedding 双层缓存：L1 cachetools (TTL 1h, maxsize=10000) + L2 Redis (TTL 24h)；L1 命中直接返回，L1 未命中查 L2，L2 未命中调 FlagEmbedding 后回写两层 |
| RULE-005 | 标量字段（years_of_experience, highest_education_level, city, gender）在入库时从 ResumeStructured 提取填充，支持 Milvus expr 预过滤 |
| RULE-006 | 学历映射：大专=1, 本科=2, 硕士=3, 博士=4，未知=0；highest_education_level 取 education_list 中最高值 |
| RULE-007 | Milvus Collection 在系统启动时自动创建（如不存在），创建后自动创建所有索引（向量索引 + 标量索引） |
| RULE-008 | Hybrid Search 必须同时传入 Dense 和 Sparse 两个 AnnSearchRequest，通过 RRFRanker(k=60) 融合 |
| RULE-009 | Hybrid Search 仅在 Small Chunk 级别执行（chunk_level == 'small'） |
| RULE-010 | Small→Big 召回：检索命中 Small Chunk 后，通过 parent_chunk_id 查找 Parent Chunk 作为 LLM 上下文 |
| RULE-011 | Parent Chunk 不可用时（数据异常），降级使用 Full Resume Chunk 作为上下文 |
| RULE-012 | 批量写入时统一 flush（不再每批 flush），提升批量入库性能 |
| RULE-013 | 批量 Embedding 使用 FlagEmbedding batch encode（batch_size=32），而非逐条调用 |
| RULE-014 | Resume 级去重：同 resume_id 的多个 Small Chunk 只保留最高分的，避免同一简历多次出现在结果中 |
| RULE-015 | 标量字段默认值：years_of_experience=0, highest_education_level=0, city="", gender="" |
| RULE-016 | Sparse 向量必须是非空的 dict{int: float}，禁止使用空 dict 或从 dense 派生的伪 sparse |
