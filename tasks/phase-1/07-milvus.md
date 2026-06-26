# T-008: Milvus 连接 + resume_chunks Collection 创建

## 基本信息
- 对应 Spec: specs/vector-index/00-overview.md (02-data-model), docs/tech-decision.md 决策项 4
- 对应 AC: vector-index AC-001~AC-008
- 依赖: T-001, T-002
- 预计工时: 1 天
- **🔴 关键路径节点**: 本任务阻断 T-015→T-019→T-020→T-021→T-022→T-023→T-027→T-030→T-034→T-039→T-042（共 15 个下游任务）。失败将导致整个检索推荐链路不可用。
- 变更记录: v1.1 — 对齐 Tier M 迭代（Multi-Chunk + 双向量），修正 Schema 字段、维度、Collection 名称

## 输入
- docs/tech-decision.md（决策项 4: Milvus Standalone）
- docker-compose.yml（来自 T-001，确认 Milvus 服务配置）
- src/common/config.py（来自 T-003，Milvus 连接配置）
- specs/vector-index/00-overview.md（**02-data-model** — Collection Schema 定义）

## 输出
- src/vector_index/connection.py
- src/vector_index/schema.py
- src/vector_index/index.py
- tests/unit/test_vector_index.py

## 实现要求
1. 创建 src/vector_index/connection.py：
   - Milvus 连接管理，支持双模式：
     - **Standalone 模式**：连接 docker-compose 中的 Milvus（开发/生产环境）
     - **Lite 模式**：使用 pymilvus 的 Milvus Lite（本地单测 / CI 环境，无需 Milvus Server）
   - **⚠️ 双环境一致性守卫**: pymilvus 版本必须与 Milvus Standalone 镜像版本对齐（均 2.4.x）。Lite 和 Standalone 对 SPARSE_FLOAT_VECTOR + SPARSE_INVERTED_INDEX 的行为在不同版本间可能存在微妙差异（如 Sparse Index 创建参数、Hybrid Search 的 RRF 融合精度）。CI 中必须同时运行 Lite 模式单测和 Standalone 模式集成测试，确保双环境结果一致。
   - 连接模式通过配置切换（MILVUS_URI）
   - 连接健康检查方法
   - 连接池/会话管理
2. 创建 src/vector_index/schema.py：
   - 定义 Milvus Collection Schema，**严格对齐** specs/vector-index/00-overview.md 中的 02-data-model：
     - id (INT64, 主键, auto_id)
     - chunk_id (VARCHAR(64), 唯一索引) — 格式: {resume_id}:{level}:{index}
     - 
esume_id (VARCHAR(64), 索引) — 关联 MongoDB
     - chunk_level (VARCHAR(16), 索引) — "small" / "parent" / "full"
     - parent_chunk_id (VARCHAR(64), 索引) — Small Chunk 的父 Chunk ID，parent/full 级别为空
     - section_type (VARCHAR(32), 索引) — "education" / "experience" / "project" / "skill" / "other"
     - dense_vector (FLOAT_VECTOR, **维度 1024**) — BGE-M3 Dense 向量（**注意：不是 1536，BGE-M3 固定输出 1024 维**）
     - sparse_vector (SPARSE_FLOAT_VECTOR) — BGE-M3 Sparse 向量（词级稀疏向量）
     - content (VARCHAR(65535)) — Chunk 文本内容
     - metadata (JSON) — {candidate_name, city, skills, experience, education, sequence_index}
   - Collection 命名：
esume_chunks（前缀从配置读取）
3. 创建 src/vector_index/index.py — VectorIndex 类：
   - create_collection() -> None — 自动创建 Collection（幂等，已存在则跳过）
   - create_indexes() -> None — 创建双向量索引：
     - Dense: HNSW, metric=COSINE, ef_construction=256, M=16
     - Sparse: SPARSE_INVERTED_INDEX, metric=IP
   - insert_chunks(chunks: list[ChunkSchema]) -> list[int] — 批量写入 Chunk 向量，返回 Milvus ID 列表
   - hybrid_search_small(query_dense: list[float], query_sparse: dict, top_k: int, expr: str | None) -> list[dict] — Small Chunk 级别混合检索
   - 
etrieve_with_parent(query_dense: list[float], query_sparse: dict, top_k: int, expr: str | None) -> list[dict] — Small→Big 召回
   - delete_chunks_by_resume(resume_id: str) -> None — 按 resume_id 删除所有 Chunk
   - drop_collection() -> None — 删除 Collection（仅测试用）
   - has_collection() -> bool — 检查 Collection 是否存在
4. 索引参数配置化：
   - HNSW: f_construction, M
   - Sparse: 索引类型（SPARSE_INVERTED_INDEX）
   - Hybrid: RRF k 值（默认 60）
   - metric_type（COSINE / IP）
5. 编写单元测试：
   - Collection 创建与存在检查（幂等性）
   - 双向量 insert → hybrid_search → delete 全流程
   - chunk_level 标量过滤测试
   - Small→Big retrieve_with_parent 测试
   - Milvus Lite 模式下单元测试通过（无需 Milvus Server）
- [ ] **AC-DUAL-01**: 同一份测试用例（含 Sparse Index 创建 + Hybrid Search）在 Lite 模式和 Standalone 模式下均通过，返回结果的 Top-5 候选人集合一致
- [ ] **AC-DUAL-02**: pymilvus 版本与 milvusdb/milvus Docker 镜像大版本对齐（均为 2.4.x），版本号记录在 .env 中

## 验收检查点

### 前置确认
- [ ] T-001 已完成（docker-compose.yml 存在，Milvus 服务定义正确）
- [ ] T-002 已完成（项目骨架存在）
- [ ] docs/tech-decision.md 已读取（决策项 4）
- [ ] specs/vector-index/00-overview.md 已读取（02-data-model）

### AC 验收
- [ ] 连接 docker-compose 中的 Milvus Standalone 成功
- [ ] create_collection() 幂等（重复调用不报错）
- [ ] Collection Schema 包含 dense_vector (FLOAT_VECTOR 1024) 和 sparse_vector (SPARSE_FLOAT_VECTOR) 两个向量字段
- [ ] 双向量 insert → hybrid_search_small → delete 全流程通过
- [ ] 
etrieve_with_parent 返回结果包含 small_chunk + parent_chunk
- [ ] Milvus Lite 模式下单元测试通过（无需 Milvus Server）
- [ ] **AC-DUAL-01**: 同一份测试用例（含 Sparse Index 创建 + Hybrid Search）在 Lite 模式和 Standalone 模式下均通过，返回结果的 Top-5 候选人集合一致

### 代码质量
- [ ] 异常使用统一错误码体系（T-004）
- [ ] 连接模式可配置切换
- [ ] 单元测试全部通过
- [ ] 向量维度硬编码为 1024（BGE-M3），不使用可变配置避免维度不一致

### Spec 一致性
- [ ] Collection Schema 字段与 specs/vector-index/00-overview.md 02-data-model 完全一致
- [ ] Collection 名称为 
esume_chunks（非旧版 
esumes）
- [ ] 向量维度为 **1024**（BGE-M3 Dense），非 1536
- [ ] 包含 SPARSE_FLOAT_VECTOR 类型的 sparse_vector 字段
- [ ] Dense 索引为 HNSW，Sparse 索引为 SPARSE_INVERTED_INDEX
- [ ] Milvus 使用 Standalone 模式（docker-compose）
- [ ] pymilvus 版本 >= 2.4.6（与 Milvus Standalone 2.4.x 对齐）

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry < 3 → 修复 | retry = 3 → BLOCKED
