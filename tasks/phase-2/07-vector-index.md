# T-015: Embedding 生成 + 向量写入

## 基本信息
- 对应 Spec: specs/vector-index/00-overview.md (REQ-001~010 章节) REQ-001~REQ-005
- 对应 AC: AC-001~AC-003
- 依赖: T-008, T-012
- 预计工时: 2 天
- **🔴 关键路径节点**: 本任务阻断 T-019→T-020→T-021→T-022→T-023→T-027→T-030→T-034→T-039→T-042（共 12 个下游任务）。若向量写入失败，整个 Hybrid Retrieval 链路将无法验证。

## 输入
- `specs/vector-index/00-overview.md (REQ-001~010 章节)` — 向量索引完整需求
- `specs/vector-index/00-overview.md (02-data-model 章节)` — 向量数据模型
- `src/vector_index/connection.py` — Milvus 连接管理（T-008 产出）
- `src/resume_parser/chunk_builder.py` — Chunk 层级构建器（T-012 产出，含 Small/Parent/Full 三层 Chunk）
- `src/resume_parser/schemas.py` — Resume 结构化数据（T-011 产出）

## 输出
- `src/vector_index/embedding_generator.py` — Embedding 生成模块
- `src/vector_index/vector_writer.py` — 向量写入模块
- `src/vector_index/index_manager.py` — 索引管理模块
- `tests/vector_index/test_embedding_generator.py` — Embedding 测试
- `tests/vector_index/test_vector_writer.py` — 向量写入测试

## 实现要求
1. 使用 BGE-M3 模型生成 Dense Embedding（1024维）和 Sparse Embedding（词级稀疏向量）
2. 将 T-012 产出的 ChunkSchema 列表（Small/Parent/Full 三层 Chunk）逐个生成向量并写入 Milvus，每个 Chunk 包含完整的 chunk_level、parent_chunk_id、section_type 元数据
3. 向量写入 Milvus Collection `resume_chunks`，每条记录必须包含 dense_vector (1024维) + sparse_vector + chunk_level + parent_chunk_id + section_type + content + metadata
4. 支持增量更新：当简历重新解析时，删除旧向量并写入新向量（upsert 语义）
5. 批量写入优化：单次写入不超过 500 条，超过则分批
6. Embedding 生成有缓存机制：相同文本不重复计算（基于 content hash）
7. 索引管理：支持创建/删除集合、重建索引、查看集合统计信息
8. 关键设计决策：选择 BGE-M3 而非 OpenAI Embedding，因为 BGE-M3 原生支持 Dense+Sparse 双向量
9. 禁止事项：禁止在向量元数据中存储 PII 明文；禁止单次批量写入超过 500 条

## 验收检查点

### 前置确认
- [ ] T-008（Milvus 客户端）已完成
- [ ] T-012（段落切分）已完成
- [ ] 容器环境已启动
- [ ] Milvus 服务可访问
- [ ] BGE-M3 模型已部署或 API 可访问

### AC 验收
- [ ] AC-001: 简历解析后能自动生成 Embedding 并写入 Milvus，Dense 和 Sparse 向量均正确
- [ ] AC-002: 增量更新时旧向量被正确删除，新向量写入成功
- [ ] AC-003: 向量元数据（resume_id, segment_id, segment_type）正确关联

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] BGE-M3 模型地址从 config 读取
- [ ] 批量写入有分批逻辑
- [ ] 缓存命中率可监控
- [ ] 错误处理：Milvus 连接失败有重试机制

### Spec 一致性
- [ ] 向量维度与 `specs/vector-index/00-overview.md (02-data-model 章节)` 一致（1024维）
- [ ] Milvus 集合 schema 与 spec 定义一致
- [ ] Hybrid Index 类型与 REQ-003 一致

- [ ] 写入 Milvus 的每条记录包含 chunk_level（small/parent/full）和 parent_chunk_id 字段
- [ ] Small Chunk 的 parent_chunk_id 正确指向 Parent Chunk 的 chunk_id
- [ ] chunk_id 格式为 {resume_id}:{level}:{index}，与 chunk_builder 输出一致
- [ ] Collection 名称为 resume_chunks（非 resume_chunks）

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
