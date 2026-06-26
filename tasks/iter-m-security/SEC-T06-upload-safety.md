# SEC-T06: 文件上传安全校验

## 基本信息
- **对应 Spec**: SEC-REQ-007, SEC-RULE-006
- **对应 AC**: AC-SEC-007
- **依赖**: SEC-T05
- **预计工时**: 0.5 天
- **优先级**: P1

## 输入
- `src/api/v1/upload.py`（当前无类型/大小校验；104-123 行 try/except 吞异常返回 success=False）
- `src/common/errors.py`（RESUME_003=422, RESUME_004=413 已定义）

## 输出
- 修改 `src/api/v1/upload.py` — 增加三重校验；移除 try/except 包裹
- `tests/security/test_upload_safety.py` — 新增

## 实现要求
1. 在 `content = await file.read()` 之后、MD5 去重之前插入校验：
   ```python
   from pathlib import Path
   MAX_SIZE = 10 * 1024 * 1024
   ALLOWED_EXT = {".pdf", ".docx", ".json"}
   ALLOWED_MIME = {
       "application/pdf",
       "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
       "application/json",
   }
   ext = Path(file.filename or "").suffix.lower()
   if ext not in ALLOWED_EXT:
       raise ValidationError(error_code=ErrorCode.RESUME_003, detail=f"不支持的格式: {ext}")
   if len(content) > MAX_SIZE:
       raise ValidationError(error_code=ErrorCode.RESUME_004, detail="文件超过 10MB")
   if file.content_type and file.content_type not in ALLOWED_MIME:
       raise ValidationError(error_code=ErrorCode.RESUME_003, detail=f"MIME 不允许: {file.content_type}")
   ```
2. **移除 104-123 行的 `except ValidationError` 和 `except Exception` 块**，让异常冒泡到全局处理器。现有逻辑把校验异常吞为 HTTP 200 + `success=False`，导致 413/422 无法正确返回
3. 移除后，函数体不需要外层 try（或保留 try 仅处理已知业务异常并 re-raise）

## 验收检查点
- [ ] 上传 11MB PDF 返回 413 + RESUME_004
- [ ] 上传 .exe 返回 422 + RESUME_003
- [ ] 上传 .pdf 但 MIME=image/jpeg 返回 422 + RESUME_003
- [ ] 上传合法 .pdf ≤10MB 返回 200
- [ ] upload.py 无 104-123 行 try/except 吞异常
- [ ] 校验在 MD5 去重之前执行
- [ ] `tests/security/test_upload_safety.py` 覆盖以上场景通过

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
