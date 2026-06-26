# T-019: Hybrid Retrieval（Small Chunk 级别）

## 基本信息
- 对应 Spec: specs/recommendation-engine/01-requirements.md REQ-001~REQ-003, REQ-013
- 对应 AC: AC-001~AC-003, AC-015
- 依赖: T-015, T-016
- 预计工时: 2.5 天
- 变更记录: v1.1 — 对齐 Tier M 迭代：(1) 分区检索→标量过滤（chunk_level）；(2) 检索粒度从简历级改为 Small Chunk 级；(3) 新增空查询防御 AC

## 输入
- specs/recommendation-engine/01-requirements.md — 检索需求（REQ-001~REQ-003, REQ-013）
- specs/recommendation-engine/02-data-model.md — 检索结果数据模型
- specs/recommendation-engine/04-business-rules.md — RULE-001（Hybrid Retrieval 执行策略）
- src/vector_index/embedding_generator.py — Embedding 生成（T-015 产出）
- src/vector_index/vector_writer.py — 向量写入（T-015 产出）
- src/intent_router/slot_extractor.py — Slot 提取（T-016 产出）

## 输出
- src/recommendation_engine/hybrid_retriever.py — 混合检索模块
- src/recommendation_engine/dense_search.py — Dense 向量检索
- src/recommendation_engine/sparse_search.py — Sparse 向量检索
- src/recommendation_engine/rrf_merger.py — RRF 融合排序
- src/recommendation_engine/query_builder.py — 查询文本构建（含空查询守卫）
- 	ests/retrieval/test_hybrid_retriever.py — 混合检索测试
- 	ests/retrieval/test_query_builder.py — 查询构建测试（含空查询用例）

## 实现要求
1. **查询文本构建**（uild_query_text）：
   - 从 Slots 中提取 job_title + skills + xperience + industry 拼接为查询文本
   - **空查询守卫**：当 Slots 全部为空或拼接结果为空字符串时，抛出 InvalidQueryError（错误码 EMPTY_QUERY），**严禁向 Milvus 发起无意义查询**（会导致全表扫描）
   - 去停用词
2. **Dense 检索**：使用 BGE-M3 Dense 向量（1024 维）在 Milvus 中执行 ANN 搜索，返回 Top-K（默认 50）
3. **Sparse 检索**：使用 BGE-M3 Sparse 向量在 Milvus 中执行稀疏搜索，返回 Top-K（默认 50）
4. **RRF 融合**：对 Dense 和 Sparse 结果使用 Reciprocal Rank Fusion 合并，公式 score = 1/(k+rank)，k 默认 60
5. **检索范围限定**：仅在 Small Chunk 级别执行，通过 Milvus **标量过滤**（xpr="chunk_level == 'small'"）实现。**注意：不使用 Milvus 原生 Partition，而是基于 chunk_level 标量字段过滤**（与 specs/vector-index/00-overview.md 02-data-model 中的 Schema 一致）
6. **Small→Big 上下文聚合**（RULE-010）：
   - 检索命中 Small Chunk 后，按 esume_id 分组，取组内最高 hybrid_score
   - 通过 parent_chunk_id 查找 Parent Chunk 作为 LLM 上下文
   - 若 Parent Chunk 不存在，降级使用 Full Resume Chunk
7. 检索结果返回 RetrievalResult：esume_id、chunk_id、chunk_level、parent_chunk_id、content、score、ank
8. 性能要求：单次检索 < 500ms（P95）
9. 关键设计决策：选择 RRF 而非简单加权求和，因为 RRF 对不同量纲的分数有更好的归一化效果
10. 禁止事项：禁止单独使用 Dense 或 Sparse 检索作为最终结果（必须融合）；禁止在检索层做业务过滤（过滤在 T-020 层执行）

## 验收检查点

### 前置确认
- [ ] T-015（Embedding + 向量写入）已完成
- [ ] T-016（意图识别）已完成
- [ ] 容器环境已启动
- [ ] Milvus 中已有 Small Chunk 级别的测试向量数据

### AC 验收
- [ ] AC-001: 输入"找3年Java经验的候选人"，Dense 和 Sparse 检索均在 Small Chunk 级别执行，RRF 融合后排序合理
- [ ] AC-002: 检索结果包含 esume_id、chunk_id、score、ank、parent_chunk_id 字段
- [ ] AC-003: 检索延迟 P95 < 500ms
- [ ] AC-015: Milvus 连接超时或查询超时时，返回统一错误码 VECTOR_SEARCH_TIMEOUT，触发降级路径
- [ ] **AC-016（新增）**: 当 uild_query_text() 输入的 Slots 全部为空或拼接结果为空字符串时，抛出 InvalidQueryError（错误码 EMPTY_QUERY），不向 Milvus 发起检索
- [ ] **AC-017（新增）**: 检索通过 xpr="chunk_level == 'small'" 标量过滤实现 Small Chunk 范围限定，不使用 Milvus 原生 Partition

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] RRF k 参数可配置
- [ ] Top-K 参数可配置
- [ ] 检索结果有日志记录（query hash、结果数量、耗时）
- [ ] 类型标注完整
- [ ] 空查询守卫有独立单元测试

### Spec 一致性
- [ ] RRF 融合公式与 REQ-002 一致（k=60）
- [ ] RetrievalResult 结构与 specs/recommendation-engine/02-data-model.md 一致
- [ ] 检索范围为 Small Chunk 级别，通过 chunk_level 标量过滤实现（与 RULE-001 第 6 条一致）
- [ ] Small→Big 聚合逻辑与 RULE-010 一致
- [ ] **不使用** Milvus 原生 Partition（与 specs/vector-index/00-overview.md Schema 设计一致）

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
