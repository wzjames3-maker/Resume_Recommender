# HR 七期规格：简历下载/原文查看、候选人合并与重复检测

日期：2026-08-13
状态：已批准

## 背景

HR 模块已完成简历上传与异步解析，但候选人简历无法查看/下载原文件；候选人无重复检测，手工录入或多次上传可能产生重复档案；重复档案无法合并。本期间 HR 补齐：简历下载与原文查看、候选人重复标记与编辑查重、候选人合并（含关系迁移与指派冲突保护）。

**范围外**：姓名模糊相似度检测（仅精确 phone/email）、批量合并、合并历史审计、任务自动重试（六期范围外）、简历上传历史页。

## 1. 简历下载与原文查看

### 1.1 `GET /workspace/{wid}/hr/resumes/{resume_id}/download`

- `@member_required`，`authentication_classes = [TokenAuth]`。
- 按 id 取 `ResumeFile`（限工作区；不存在 → `NotFound404`）。
- `os.path.exists(resume.file_path)` 为假 → `NotFound404(404, "File not found")`。
- 返回 `FileResponse(open(file_path, "rb"), content_type=..., as_attachment=True, filename=resume.file_name)`：
  - docx → `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
  - txt → `text/plain`
  - 其他扩展名 → `application/octet-stream`
- 文件读取失败（IOError）→ `AppApiException(500, "文件读取失败")`。
- 视图返回前不关闭文件（FileResponse 负责关闭；用 `with` 会提前关闭——按 FileResponse 惯例打开后交给响应）。

### 1.2 `GET /workspace/{wid}/hr/resumes/{resume_id}/content`

- `@member_required`，`authentication_classes = [TokenAuth]`。
- 按 id 取 `ResumeFile`（限工作区；不存在 → 404）。
- `os.path.exists(resume.file_path)` 为假 → 404「File not found」。
- 实时提取：docx → `extract_text_from_docx`，txt → `extract_text_from_txt`（`apps/hr/services/resume_parser.py` 既有函数）。
- 提取异常 → `AppApiException(400, "简历内容提取失败")`。
- 返回 `{"content": text}`。

### 1.3 前端

- 候选人操作列新增「简历」按钮（`@member_required` 可见，与「加入职位」同权限）→ dialog：
  - 调 `list_candidate_resumes(candidate_id)` 展示列表（file_name、extension、file_size、状态、时间）。
  - 每行「查看」→ content dialog（`<pre>` 展示文本）；「下载」→ 触发浏览器下载（`window.open` 或 a 标签指向 download URL；项目内其他下载先例以实际为准，实现时确认）。

## 2. 重复检测

### 2.1 判定规则

- 同工作区；**手机号**（非空）相等 或 **邮箱**（非空）相等（忽略大小写比较邮箱）。
- 排除自身。
- 姓名/技能不做相似度匹配。

### 2.2 列表标记（`page_candidates` 扩展）

- 返回每条记录追加 `duplicate_ids: [str, ...]`（按 2.1 规则命中其他候选人的 id 列表）。
- 实现：对当前页候选人的非空 phone 集合与 email 集合各做一次查询：`filter(workspace_id=..., phone__in=phones)`（精确等值分组）+ `filter(workspace_id=..., email__in=emails)`（精确查询后 Python 侧按 lowercase 归组，兼容录入时大小写差异）。汇总去重后得 duplicate_ids（排除自身）。
- 空列表时返回 `[]`。

### 2.3 编辑查重 `POST /workspace/{wid}/hr/candidates/check-duplicate`

- `@member_required`，`authentication_classes = [TokenAuth]`。
- body：`{phone?: string, email?: string, exclude_id?: string}`。
- phone 与 email 均缺 → 返回 `{"candidates": []}`（不报错）。
- 按 2.1 规则查同工作区命中候选人（`exclude_id` 排除自身），返回 `{"candidates": [{id, name, phone, email, current_city}]}`，上限 20 条。
- 用于新建/编辑保存前提示。

### 2.4 前端

- 列表行：`duplicate_ids` 非空 → 显示「疑似重复」tag + `el-tooltip` 展示命中数量（如「与 2 名候选人重复」）。
- 新建/编辑候选人对话框保存：先调 `check-duplicate`（带表单 phone/email + exclude_id=当前编辑 id）→ 命中 → `MsgConfirm`「发现疑似重复候选人，是否继续保存？」→ 确认后走原保存流程。

## 3. 候选人合并

### 3.1 `POST /workspace/{wid}/hr/candidates/{primary_id}/merge`

- `@manage_required`，`authentication_classes = [TokenAuth]`。
- body：`{secondary_id: str}`。
- 校验（顺序）：
  1. 主、从候选人均存在且同工作区（否则 `NotFound404`）。
  2. `primary_id == secondary_id` → `AppApiException(400, "不能与自己合并")`。
  3. 从候选人的有效指派（`ACTIVE_ASSIGNMENT_STATUSES` 内）中存在与主候选人**同 job** 的指派 → `AppApiException(400, "存在与主候选人冲突的有效指派，请先调整")`。
- 合并（`transaction.atomic`）：
  1. 字段：主候选人已有值（非空）优先；主为空时用从候选人非空值补齐（name/email/phone/current_city/target_city/highest_degree/years_experience/source）。
  2. `skills`：两方并集（保留主方顺序，从方去重追加）。
  3. `note`：主 note 与从 note 拼接（非空段用 `\n` 连接）。
  4. 关系迁移：`ResumeFile.objects.filter(candidate=secondary).update(candidate=primary)`；`CandidateAssignment.objects.filter(candidate=secondary).update(candidate=primary)`（Interview 经 FK 随指派自动归属，无需改动）。
  5. 删除从候选人 `secondary.delete()`。
- 返回合并后主候选人完整详情（含 assignments——复用 `get_candidate` 输出）。
- 从候选人可为 ARCHIVED（归档档案可合并）。

### 3.2 前端

- 候选人操作列「合并」按钮（`@manage_required` 可见）→ dialog：
  - 展示当前候选人（主）。
  - 目标候选人选择：调 `getCandidates({page_size: 100})` 列表，排除自身（前端过滤）。
  - 提交 `merge` → 成功提示 + 刷新。

## 4. 测试（TDD）

### 4.1 下载与查看（`ResumeDownloadTests`）

- 下载：造 ResumeFile（临时文件写入内容）→ 200、`Content-Disposition` 含 `attachment` 与文件名、响应体与文件内容一致。
- 文件缺失：file_path 指向不存在路径 → 404。
- 跨工作区：resume 属于 workspace-b → 404。
- content：txt 内容正确返回；损坏 docx（非 zip 内容）断言提取失败 400；docx 成功路径由六期任务函数测试间接覆盖（不构造最小 docx）。

### 4.2 重复检测（`DuplicateDetectionTests`）

- `page_candidates`：同手机号两个候选人 → 互为 duplicate_ids；同邮箱（大小写不同）→ 命中；无重复 → `[]`；排除自身。
- `check_duplicate`：phone 命中、email 命中、exclude_id 排除、空参数返回 `[]`、上限 20。

### 4.3 合并（`CandidateMergeTests`）

- 成功合并：字段补充（主空从有）、主有值不被覆盖、skills 并集、note 拼接、简历迁移、指派迁移（从的指派 candidate 变主）、从删除、Interview 仍指向迁移后的指派。
- 冲突指派：主、从各有同 job 有效指派 → 400「冲突」；不同 job 有效指派 → 正常合并。
- 同人 → 400。
- 跨工作区 → 404。
- 非 manage → `AppUnauthorizedFailed`。
- 已归档从候选人可合并。

### 4.4 回归与构建

- `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb`：原 86 项 + 新增全过。
- `manage.py check`、`makemigrations --check --dry-run`（无新迁移预期）。
- 前端 `vue-tsc --build`、双 `vite build`、裁剪端点产物扫描（新增端点确认）。

## 5. 验收标准

- 候选人简历可下载原文件、可查看提取文本；跨工作区与缺失文件正确 404。
- 列表标记疑似重复、编辑保存前查重提示，均可用。
- 合并迁移完整（字段/技能/备注/简历/指派/面试），冲突指派被拒且提示明确，从候选人删除。
- 全部自动化测试通过，前端可构建。

## 6. 提交

- 规格：`docs(人事): 制定简历查看合并与查重规格`
- 计划：`docs(人事): 制定简历查看合并与查重实现计划`
- 后端：`feat(人事): 提供简历查看下载与候选人查重合并能力`（按任务拆分多个 feat）
- 前端：`feat(人事): 新增简历查看与候选人合并页面`
- 验收：`test(人事): 记录简历查看合并与查重验收`
