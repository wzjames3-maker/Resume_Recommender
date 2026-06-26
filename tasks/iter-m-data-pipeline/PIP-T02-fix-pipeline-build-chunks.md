# PIP-T02: 修复 full_pipeline.py 方法名 + 清理离线脚本

## 基本信息
- **对应 Spec**: VEC-INDEX REQ-002
- **依赖**: PIP-T01
- **预计工时**: 0.5 天
- **优先级**: P0

## 问题
`scripts/pipeline/full_pipeline.py:67` 调用 `chunk_builder.build_chunks(resume)`，但 `ChunkBuilder` 只有 `build(segments, resume_id, full_text)` 方法。离线脚本必然抛 `AttributeError`。

## 实现要求

### 1. 修复 `scripts/pipeline/full_pipeline.py`
将 `t_index_resume()` 中的调用改为:
```python
# 旧: chunks = chunk_builder.build_chunks(resume)
# 新:
segmentation_result = segmenter.segment(resume.raw_text or "")
chunk_result = chunk_builder.build(
    segments=segmentation_result.segments,
    resume_id=resume.id,
    full_text=resume.raw_text or "",
)
ids = writer.write_chunks(chunk_result.chunks, resume.id)
```

### 2. 抽取公共函数
在 `src/resume_parser/` 或 `src/services/` 下创建 `indexing.py`，封装:
```python
def index_resume(resume_id: str, raw_text: str) -> int:
    """对一份简历执行 分段→分块→向量化，返回 chunk 数量"""
```
让 upload.py 和 pipeline 脚本共用同一入口，避免两套链路。

### 3. 更新离线脚本引用
检查 `scripts/pipeline/` 下所有脚本的 `build_chunks` 调用，统一修复。

## 验收检查点
- [ ] `full_pipeline.py` 的 `t_index_resume()` 使用正确的 `build()` 方法
- [ ] 存在 `src/services/indexing.py` 提供 `index_resume()` 公共函数
- [ ] `upload.py` 调用 `index_resume()` 而非直接调 chunk_builder
- [ ] `rg "build_chunks" scripts/` 返回零结果

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
