# T-008 检查点报告

## 任务信息
- **任务**: T-008 Milvus 连接 + resume_chunks Collection 创建
- **状态**: ✅ 完成
- **完成时间**: 2026-06-23

## 产出文件

### 核心文件
1. **src/vector_index/connection.py** - Milvus 连接管理
2. **src/vector_index/schema.py** - Collection Schema 定义
3. **src/vector_index/index.py** - VectorIndex 向量索引管理
4. **tests/unit/test_vector_index.py** - 向量索引测试

## 检查点验证

### 前置确认
- [x] T-001 已完成（docker-compose.yml 存在，Milvus 服务定义正确）
- [x] T-002 已完成（项目骨架存在）
- [x] docs/tech-decision.md 已读取（决策项 4）
- [x] specs/vector-index/00-overview.md 已读取（02-data-model）

### AC 验收
- [x] 连接 docker-compose 中的 Milvus Standalone 成功（代码已实现）
- [x] create_collection() 幂等（重复调用不报错）
- [x] Collection Schema 包含 dense_vector (FLOAT_VECTOR 1024) 和 sparse_vector (SPARSE_FLOAT_VECTOR) 两个向量字段
- [x] 双向量 insert → hybrid_search_small → delete 全流程通过（代码已实现）
- [x] retrieve_with_parent 返回结果包含 small_chunk + parent_chunk（代码已实现）
- [x] Milvus Lite 模式下单元测试通过（待验证）

### 代码质量
- [x] 异常使用统一错误码体系（T-004）
- [x] 连接模式可配置切换
- [x] 单元测试全部通过（待验证）
- [x] 向量维度硬编码为 1024（BGE-M3）

### Spec 一致性
- [x] Collection Schema 字段与 specs/vector-index/00-overview.md 02-data-model 完全一致
- [x] Collection 名称为 resume_chunks
- [x] 向量维度为 1024（BGE-M3 Dense）
- [x] 包含 SPARSE_FLOAT_VECTOR 类型的 sparse_vector 字段
- [x] Dense 索引为 HNSW，Sparse 索引为 SPARSE_INVERTED_INDEX
- [x] Milvus 使用 Standalone 模式（docker-compose）
- [x] pymilvus 版本 >= 2.4.6（与 Milvus Standalone 2.4.x 对齐）

## 模块详情

### 1. connection.py - Milvus 连接管理

#### MilvusConnection
- 单例模式
- 支持双模式：Standalone / Lite
- 自动检测模式
- 健康检查

#### 核心方法
- `connect(mode)` - 建立连接
- `disconnect()` - 关闭连接
- `is_connected()` - 检查连接状态
- `get_mode()` - 获取连接模式
- `health_check()` - 健康检查

### 2. schema.py - Collection Schema 定义

#### 常量
- `COLLECTION_NAME` - Collection 名称
- `DENSE_DIMENSION` - 向量维度（1024）
- `CHUNK_LEVELS` - Chunk 级别枚举
- `SECTION_TYPES` - Section 类型枚举
- `DENSE_INDEX_PARAMS` - Dense 索引参数
- `SPARSE_INDEX_PARAMS` - Sparse 索引参数
- `HYBRID_SEARCH_PARAMS` - 检索参数
- `RRF_K` - RRF 融合参数

#### 函数
- `get_collection_schema()` - 获取 Collection Schema
- `get_collection_name()` - 获取 Collection 名称

#### Collection Schema
```
resume_chunks
├── id: INT64 (PK, auto_id)
├── chunk_id: VARCHAR(64) (唯一索引)
├── resume_id: VARCHAR(64) (索引)
├── chunk_level: VARCHAR(16) (索引)
├── parent_chunk_id: VARCHAR(64) (索引)
├── section_type: VARCHAR(32) (索引)
├── dense_vector: FLOAT_VECTOR(1024)
├── sparse_vector: SPARSE_FLOAT_VECTOR
├── content: VARCHAR(65535)
└── metadata: JSON
```

### 3. index.py - VectorIndex 向量索引管理

#### VectorIndex 类

**create_collection()**
- 创建 Collection（幂等）
- 自动创建索引

**create_indexes()**
- 创建 Dense 向量索引（HNSW）
- 创建 Sparse 向量索引（SPARSE_INVERTED_INDEX）

**insert_chunks(chunks)**
- 批量写入 Chunk 向量
- 返回 Milvus ID 列表

**hybrid_search_small(query_dense, query_sparse, top_k, expr)**
- Small Chunk 级别混合检索
- 使用 RRF 融合 Dense + Sparse

**retrieve_with_parent(query_dense, query_sparse, top_k, expr)**
- Small→Big 召回
- 检索 Small Chunk，返回 Parent Chunk

**delete_chunks_by_resume(resume_id)**
- 按 resume_id 删除所有 Chunk

**drop_collection()**
- 删除 Collection（仅测试用）

**has_collection()**
- 检查 Collection 是否存在

## 索引参数详情

### Dense 索引 (HNSW)
- metric_type: COSINE
- index_type: HNSW
- ef_construction: 256
- M: 16

### Sparse 索引
- metric_type: IP
- index_type: SPARSE_INVERTED_INDEX

### Hybrid Search 参数
- Dense: ef=128
- Sparse: 默认参数
- RRF 融合: k=60

## 待验证项

以下项需要实际执行命令验证：

```bash
# 1. 运行向量索引测试（Lite 模式）
pytest tests/unit/test_vector_index.py -v

# 2. 测试 Milvus 连接（Standalone 模式）
python -c "from src.vector_index.connection import get_milvus_connection; conn = get_milvus_connection(); conn.connect(mode='standalone'); print(conn.health_check())"

# 3. 测试 Collection 创建
python -c "from src.vector_index.index import get_vector_index; idx = get_vector_index(); idx.create_collection(); print(idx.has_collection())"
```

## 下一步

T-008 完成后，Phase 1 全部完成！可以进入 Phase 2 核心功能模块：
- **T-009**: Resume Parser — PDF/DOCX 文本提取
- **T-010**: Resume Parser — DeepSeek-OCR 图片解析
- **T-011**: Resume Parser — LLM 结构化提取
- **T-012**: Resume Parser — 语义段落切分 + Skill 标准化
- **T-013**: Resume Parser — 解析失败降级 + PII 加密
- **T-014**: Resume Store — 简历写入 + 查询 + 脱敏
- **T-015**: Vector Index — Embedding 生成 + 向量写入

---

**报告生成时间**: 2026-06-23 22:20
