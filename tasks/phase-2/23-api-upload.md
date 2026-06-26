# T-031: FastAPI /api/v1/resumes/upload

## 基本信息
- **对应 Spec**: api-layer REQ-002
- **对应 AC**: AC-003, AC-004
- **依赖任务**: T-014（Resume Parser 模块）, T-006（FastAPI 应用骨架）
- **预计工时**: 1 天
- **优先级**: P0

## 输入
- T-014 产出的 Resume Parser 模块（PDF 解析、字段提取）
- ARQ Worker 基础设施（Redis 连接 + Worker 启动脚本）
- T-006 产出的 FastAPI 应用骨架
- API Layer Spec `03-api-contract.md` 中 REQ-002 的请求/响应定义

## 输出
- `src/api/v1/resumes.py` — 路由文件，含 `/api/v1/resumes/upload` 端点
- `src/api/v1/schemas/resume.py` — 请求/响应 Pydantic 模型
- 文件存储处理逻辑（本地 or MinIO，视 Spec 而定）
- 单元测试 `tests/api/test_upload.py`

## 实现要求

### 端点定义
```
POST /api/v1/resumes/upload
Headers: Authorization: Bearer <JWT>
Content-Type: multipart/form-data
Body:
  - file: UploadFile (PDF/DOCX/DOC, max 10MB)
  - candidate_name: str (可选)
  - tags: list[str] (可选)
Response 200:
{
  "resume_id": "uuid",
  "filename": "张三_简历.pdf",
  "status": "processing",
  "parsed_fields": { ... }
}
```

### 文件处理流程
1. 校验文件类型（仅允许 `.pdf`, `.docx`, `.doc`）
2. 校验文件大小（≤ 10MB）
3. 计算文件内容 MD5，调用 resume-store find_by_md5() 检查去重
   - 若已存在 → 直接返回已有 resume_id + status="skipped"
   - 若不存在 → 继续步骤 4~7
4. 保存文件到存储层
5. 调用 Resume Parser 解析
6. 写入 MongoDB（含 file_md5 字段）
7. 生成 Embedding 并写入 Milvus（异步 or 同步，视架构而定）
8. 实现 ARQ Worker Task（`parse_resume_task`）：接收 file_path + file_md5 + user_id，执行完整解析+入库+向量化流程
9. 实现 `/api/v1/tasks/{task_id}` 进度查询端点（读取 Redis Hash `task:{task_id}`）
10. Redis 不可用时降级为同步解析（直接调用 parse_resume）

### 错误处理
- 400: 文件类型不支持
- 413: 文件过大
- 202 Accepted: 任务已入队（正常异步响应）
- 422: 解析失败（通过 /tasks/{task_id} 查询，非同步返回）
- 500: 存储/写入异常
- 200 (skipped): 文件已存在（MD5 去重命中），返回已有 resume_id

## 验收检查点

### 前置确认
- [ ] T-014 已完成并通过验收（Resume Parser 可用）
- [ ] T-006 已完成并通过验收
- [ ] MongoDB 和 Milvus 连接正常

### AC 验收
- [ ] **AC-003**: 上传 PDF 文件，返回解析后的结构化数据（姓名、技能、经历等字段）
- [ ] **AC-004**: 上传不支持的文件类型时返回 400 错误；上传过大文件返回 413 错误
- [ ] **AC-005**: 上传已存在的文件（MD5 相同），返回 status="skipped" + 已有 resume_id，不重复入库
- [ ] **AC-006**: 上传新文件（MD5 不同），正常解析入库

### 代码质量
- [ ] 文件类型/大小校验在路由层完成，不传入 Parser
- [ ] 异常时已上传的文件有清理机制（不留垃圾文件）
- [ ] 单元测试覆盖率 ≥ 80%（含正常上传 + 异常路径）
- [ ] `ruff check` / `mypy` 无报错

### Spec 一致性
- [ ] 请求/响应字段与 `03-api-contract.md` REQ-002 完全一致
- [ ] 文件大小限制、类型限制符合 Spec 定义
- [ ] 解析结果字段与 Resume Parser 输出一致

### 通过判定
- [ ] 所有 AC 验收项通过
- [ ] 手动 curl 上传 PDF 测试通过
- [ ] 异常路径（错误类型、过大文件）返回正确状态码
