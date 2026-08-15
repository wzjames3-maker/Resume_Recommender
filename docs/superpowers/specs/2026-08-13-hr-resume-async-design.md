# HR 六期规格：Celery 异步化简历解析与批量上传队列

日期：2026-08-13
状态：已批准

## 背景

简历解析目前同步执行：上传接口在请求内完成文件存储、文本提取、解析与候选人创建，大批量上传时请求阻塞、前端无进度反馈。本期间 HR 引入内核 Celery 异步任务：每个文件一个解析任务，上传立即返回，前端轮询任务状态。

**范围外**：任务自动重试、上传历史页、简历下载与候选人合并（七期）、LLM 相关能力（五期已交付）。

## 1. 异步任务（新增 `apps/hr/task/resume.py`）

### 1.1 任务定义

```python
@celery_app.task(base=QueueOnce, once={"keys": ["resume_id"]}, name="celery:hr_parse_resume")
def parse_resume_task(resume_id):
    ...
```

- 导入：`from ops import celery_app`（与 `knowledge/task/embedding.py` 同款）、`from celery_once import QueueOnce`。
- `once keys` 为 `resume_id`：同一简历防重复派发/执行。
- 注册：`apps/ops/celery/__init__.py` 的 `imports` 列表追加 `'hr.task.resume'`（与 `knowledge.task.*` 同款，显式导入因任务不在 `<app>/tasks.py`）。
- 任务函数保持普通函数形态（可同步调用，便于测试直接 `.run()`）。

### 1.2 任务流程

1. 取 `ResumeFile`（按 id；不存在则直接返回，不抛错）。
2. 按 `extension` 提取文本（docx → `extract_text_from_docx`，txt → `extract_text_from_txt`）。
3. `parse_resume_text(text)` 解析。
4. 在 `transaction.atomic` 内：创建 `Candidate`（name 兜底 `file_name`、skills/source/note 等回填，与现状 `upload_resumes` 的建人逻辑一致；`source` 取 `ResumeFile.source_channel`；`user_id` 取 `ResumeFile.user_id`）→ 更新 `ResumeFile`：`status=SUCCESS`、关联 `candidate`、清空 `error_message`。原子性保证不产生「已建候选人但简历未标记成功」的孤儿状态。
5. 任何异常（提取/解析/建库）：更新 `ResumeFile` `status=FAILED` + `error_message=str(exc)`；**不自动重试**（用户可删除后重新上传）。若异常发生在更新 `ResumeFile` 自身时（DB 级故障），任务抛出由 Celery 记录失败，不做额外处理。
6. 任务内不打印堆栈到响应，错误信息写入 `error_message`。

### 1.3 与既有服务的关系

- 任务内建候选人与更新简历的逻辑从 `RecruitmentService.upload_resumes` 提取为可复用函数（如 `hr/services/resume_parser.py` 新增 `persist_parsed_resume`，或在任务模块内实现同款逻辑）。
- **最小改动原则**：优先在任务模块内复用现有解析工具函数（`extract_text_from_docx` / `extract_text_from_txt` / `parse_resume_text`），建人与更新逻辑与 `upload_resumes` 现状保持等价（字段、错误处理一致），不强制抽取抽象。

## 2. 上传接口改造（`apps/hr/views/recruitment.py` ResumeAPI POST）

保持同步前置，仅解析部分异步化：

1. `source_channel` 校验、`extension`（docx/txt）校验、`size ≤ 20MB` 校验（同现状）。
2. **sha256 计算与查重（同步）**：哈希 <1s，duplicate 判定仍同步返回，与现状一致。
3. duplicate 命中：返回现有记录（`duplicate=True`，同现状），**不建 PENDING 记录、不派发任务**。
4. 新文件：`shutil.move` 存文件 → 建 `ResumeFile`（`status=PENDING`，其余字段同现状）→ `parse_resume_task.delay(resume_id)`。
   - `AlreadyQueued` 异常 → `AppApiException(500, "任务已存在，请稍后查询")`。
   - 派发失败（delay 抛其他异常）：将 `ResumeFile` 置为 `FAILED` + `error_message`，records 中该条返回 `status=FAILED` + `error_message`（不抛错，不让整个上传失败）。
5. 返回 records：新文件 `status=PENDING`、`duplicate=False`、`candidate_id=None`；duplicate 记录同现状。
6. `RecruitmentService.upload_resumes` 的签名与返回结构保持兼容（records 列表字段不变），解析与建人逻辑移除。
7. **已知限制（与现状一致）**：并发上传同一文件可能同时通过查重并各自建候选人（DB 层 sha256 唯一约束实际已存在——迁移 0003，并发重复表现为 IntegrityError 未捕获而报 500，已在后续保存查重防护中修复）；属既有行为，六期不处理。

## 3. 状态查询接口

### 3.1 `GET /workspace/{wid}/hr/resumes/batch-status?ids=a,b,c`

- `@member_required`，`authentication_classes = [TokenAuth]`。
- `ids` 必填，逗号分隔；空或非法格式 → 400「ids is required」；**超过 200 个 → 400「too many ids」**。
- 查询 `ResumeFile`（按 id，限制在工作区）；**不存在的 id 直接忽略**，仅返回存在记录的列表。
- 返回 `[{resume_id, file_name, status, candidate_id, error_message}]`。
  - **不返回 `duplicate` 字段**（现状未持久化该信息）；前端「重复」提示沿用上传时同步返回的 duplicate 记录（不进入轮询）。

### 3.2 视图归属

- 新增 `ResumeBatchStatusAPI`（`apps/hr/views/recruitment.py` 或独立视图文件），注册 `apps/hr/urls.py` 与 `views/__init__.py`。

## 4. 前端（候选页上传对话框）

- `handleResumeFiles` 改造：
  1. 上传请求返回后，`uploadResults` 直接展示：duplicate 记录显示「重复」（同步已知）；新文件显示「解析中」（PENDING）。
  2. 收集 PENDING 记录的 `resume_id` 列表 → `setInterval` 每 1s 调 `getResumeBatchStatus(ids)`：
     - 返回记录中终态（SUCCESS/FAILED）更新对应行展示（成功/失败 + error_message）。
     - 全部终态或 60s 超时 → `clearInterval` 停止轮询。
     - 对话框关闭（`uploadDialogVisible` 变 false）→ 停止轮询。
  3. 轮询中/结束后的候选人列表刷新：**全部结束后** `refresh()` 一次（避免每轮都刷新）。
  4. 停止条件：全部终态、60s 超时、对话框关闭（`uploadDialogVisible` 变 false）、**组件卸载（`onUnmounted`）**——四者任一即 `clearInterval`。
- `ui/src/api/hr/recruitment.ts` 追加 `getResumeBatchStatus(ids: string[])`；`ui/src/api/type/hr.ts` 追加 `ResumeBatchStatus` 类型（可选）。
- 复用现有 `uploadResults` 展示区与「继续上传」按钮；上传对话框标题/说明提示异步解析。

## 5. 测试（TDD）

### 5.1 任务函数（`ResumeParseTaskTests`）

- 成功：建 Candidate + ResumeFile SUCCESS + 关联 candidate + error_message 清空。
- 文本提取失败（如损坏 docx）：ResumeFile FAILED + error_message 非空，不建 Candidate。
- 任务直接 `.run(resume_id)` 同步调用（不经过 broker）；resume 不存在时静默返回不抛错。

### 5.2 上传接口（`ResumeUploadAsyncTests`）

- 新文件：返回 `status=PENDING`，`ResumeFile` 落库 PENDING，`delay` 被调用（mock `hr.serializers.recruitment.parse_resume_task.delay`，派发在服务层 `upload_resumes` 内）。
- duplicate：返回 duplicate 记录，不建新 ResumeFile、不派发任务。
- 格式/大小校验 400（同现状，回归）。
- `delay` 抛 `AlreadyQueued` → 500「任务已存在」。
- `delay` 抛其他异常 → 返回 FAILED 记录且 ResumeFile 置 FAILED。

### 5.3 状态查询（`ResumeBatchStatusTests`）

- 多 id 混合（存在/不存在）→ 仅返回存在记录。
- 空 ids / 缺参 → 400。

### 5.4 既有测试适配

- `ResumeServiceTests` 中断言 `upload_resumes` 同步建候选人/SUCCESS/FAILED 的用例需改造：解析与建人断言迁移到任务函数测试（5.1），`upload_resumes` 仅保留校验/查重/落库 PENDING 断言。

### 5.5 回归与构建

- `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb`：原 76 项 + 新增全过。
- `manage.py check`、`makemigrations --check --dry-run`。
- 前端 `vue-tsc --build`、双 `vite build`、裁剪端点产物扫描。

## 6. 验收标准

- 上传响应 <1s 量级（不含解析）；新文件立即返回 PENDING 并进入轮询。
- worker 消费任务后简历状态收敛为 SUCCESS/FAILED，成功自动建候选人。
- 无 worker 运行时不阻塞上传（任务排队于 Redis）。
- 全部自动化测试通过，前端可构建；可选：启动真实 worker 端到端验证一次。

## 7. 提交

- 规格：`docs(人事): 制定简历解析异步化规格`
- 计划：`docs(人事): 制定简历解析异步化实现计划`
- 任务+服务改造+接口+测试：`feat(人事): 简历解析异步化`（可按任务拆分多个 feat）
- 前端：`feat(人事): 上传状态轮询页面`
- 验收：`test(人事): 记录简历解析异步化验收`
