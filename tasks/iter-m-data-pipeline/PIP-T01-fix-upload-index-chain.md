# PIP-T01: Upload 接入分段→分块→向量化链路

## 基本信息
- **对应 Spec**: RES-PARSER REQ-012 (新增), VEC-INDEX REQ-002
- **依赖**: 无
- **预计工时**: 1 天
- **优先级**: P0

## 问题
`src/api/v1/upload.py:103` 在 `repository.create()` 后直接 return，从未调用 segmenter/chunk_builder/vector_writer。
结果：通过 API 上传的简历永远不会进入 Milvus 向量索引。检索端 `hybrid_retriever` 查到的始终是空结果。

## 实现要求

### 1. 修改 `src/api/v1/upload.py`
在 `repository.create(user_id, request, file_md5)` 之后，`return UploadResponse(...)` 之前，插入索引链路：

```python
# 在 line 103-104 之间插入:
# 11. 语义段落切分
from src.resume_parser.segmenter import get_segmenter
segmenter = get_segmenter()
segmentation_result = segmenter.segment(extracted_doc.raw_text)

# 12. 构建 Multi-Level Chunk
from src.resume_parser.chunk_builder import get_chunk_builder
chunk_builder = get_chunk_builder()
chunk_result = chunk_builder.build(
    segments=segmentation_result.segments,
    resume_id=resume.id,
    full_text=extracted_doc.raw_text,
)

# 13. 写入向量索引
from src.vector_index.vector_writer import get_vector_writer
vector_writer = get_vector_writer()
vector_writer.write_chunks(chunk_result.chunks, resume.id)

logger.info(f"向量索引写入完成: resume_id={resume.id}, chunks={len(chunk_result.chunks)}")
```

### 2. 错误处理
- 索引链路失败时不应阻塞上传响应（简历已入库，向量可异步补写）
- 失败时记录 error 日志，但 UploadResponse 仍返回 success=True
- parse_status 增加 `indexed` / `index_failed` 状态

### 3. Spec 更新
在 `specs/resume-parser/01-requirements.md` 新增：
```
| REQ-012 | FR-002 | API 上传简历后自动触发语义分段→Chunk 构建→向量索引写入 | P0 |
```
在 `specs/resume-parser/03-api-contract.md` 更新数据流图。

## 验收检查点
- [ ] `upload.py` 的 upload_resume 函数包含索引链路调用
- [ ] 索引失败不影响上传响应（resume_id 正常返回）
- [ ] 日志包含 "向量索引写入完成" 或 "向量索引写入失败"
- [ ] `python -c "from src.api.v1.upload import router"` 无 ImportError
- [ ] 现有 upload 测试仍然通过（mock 索引链路）

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
