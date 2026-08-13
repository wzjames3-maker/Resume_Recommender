# 面试与 Offer 状态实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 持久化面试结果，支持 Offer 入职/拒绝，贯通面试管理四 Tab、简历面试状态筛选和自然语言搜人状态口径。

**架构：** 保留 `Assignment.status` 作为招聘流程状态，在 `Assignment` 增加独立的 `interview_result` 枚举。面试反馈通过服务层同步结果；未履行/取消通过独立接口写入结果。候选人列表和自然语言搜索均通过 Assignment 的 EXISTS 条件筛选，避免一人多职位重复。

**技术栈：** FastAPI、SQLAlchemy async、Alembic、PostgreSQL、React 18、TypeScript、Ant Design、Vitest。

---

### 任务 1：新增面试结果字段和迁移

**文件：**
- 修改：`backend/app/models/assignment.py`
- 修改：`backend/app/models/__init__.py`
- 创建：`backend/alembic/versions/9c7e2a1b4d6f_add_interview_result.py`
- 测试：`backend/tests/` 中现有 assignment/interview 测试文件

- [ ] **步骤 1：编写失败测试**

增加模型/迁移后的断言：新 Assignment 的 `interview_result is None`；四个合法值可保存；非法值被数据库/服务拒绝。

- [ ] **步骤 2：运行测试确认失败**

运行：`docker compose exec api pytest -q backend/tests -k 'assignment or interview'`

预期：新增字段和枚举相关断言失败。

- [ ] **步骤 3：实现最少模型和迁移**

新增 `InterviewResult`：`passed`、`failed`、`no_show`、`cancelled`；在 `Assignment` 添加 nullable 的 SQLAlchemy Enum 字段和索引。Alembic 从当前 head 创建 PostgreSQL enum `interview_result`，添加 nullable 列和索引，降级时删除索引、列和 enum。

- [ ] **步骤 4：运行测试确认通过**

运行：`docker compose exec api alembic upgrade head`；`docker compose exec api pytest -q backend/tests -k 'assignment or interview'`。

预期：迁移成功，既有 assignment/interview 测试通过。

### 任务 2：实现面试结果服务和 API

**文件：**
- 修改：`backend/app/services/interview_service.py`
- 修改：`backend/app/api/interviews.py`
- 修改：`backend/app/api/assignments.py`
- 修改：`backend/app/services/assignment_service.py`
- 测试：现有面试/指派测试文件，必要时创建 `backend/tests/test_interview_result.py`

- [ ] **步骤 1：编写失败测试**

覆盖：`recommend` 写入 `passed` 但不自动进入 `offer`；`reject` 写入 `failed` 并按现有规则要求淘汰原因；独立接口可写 `no_show/cancelled`；`offer -> hired`、`offer -> offer_rejected` 保持 HC 计数正确；看板返回招聘状态和面试结果。

- [ ] **步骤 2：运行测试确认失败**

运行：`docker compose exec api pytest -q backend/tests/test_interview_result.py`

预期：接口不存在或结果字段未同步导致失败。

- [ ] **步骤 3：实现服务和接口**

在 `interview_service.py` 增加结果更新函数，锁定 Assignment，校验工作区和可见性，写候选人事件。反馈同步规则：`recommend -> passed`、`reject -> failed`，`advance/hold -> None`；当 `reject` 时调用现有 transition 并要求 `reject_reason`。增加 `POST /workspaces/{ws_id}/assignments/{assignment_id}/interview-result`，body 为 `{result, reason?}`，仅允许四种枚举值；安排新轮次时清空当前结果。看板和候选人 assignment 返回 `interview_result`。补充明确的 Offer 结果接口或复用 transition，确保 offer-rejected reason 与审计事件有 API 入口。

- [ ] **步骤 4：运行测试确认通过**

运行：`docker compose exec api pytest -q backend/tests/test_interview_result.py backend/tests -k 'assignment or interview'`。

预期：所有相关测试通过，Offer reservation 在拒绝时释放、入职时转为 filled。

### 任务 3：增加候选人面试状态筛选

**文件：**
- 修改：`backend/app/api/candidates.py`
- 修改：`backend/app/services/candidate_list.py`
- 修改：`frontend/src/api/candidates.ts`
- 修改：`frontend/src/pages/CandidatesPage.tsx`
- 测试：`backend/tests/test_candidate_list.py` 或现有候选人列表测试；`frontend/src/**/*.test.*`

- [ ] **步骤 1：编写失败测试**

断言 `interview_result=passed/failed/no_show` 只返回有对应 Assignment 的候选人，多个职位指派不会重复；`cancelled` 作为参数被拒绝或不出现在前端选项。

- [ ] **步骤 2：运行测试确认失败**

运行：`docker compose exec api pytest -q backend/tests -k 'candidate_list or candidates'`

预期：接口不接受 `interview_result` 或筛选未生效。

- [ ] **步骤 3：实现筛选**

在候选人列表 API 接收 `interview_result`，校验值为前三种允许值；服务层对 `Assignment` 使用 `exists(select(...))`，同时限定 workspace。前端新增“面试状态” Select，仅显示面试通过、面试不通过、未履行面试，切换时携带 `interview_result`。

- [ ] **步骤 4：运行测试确认通过**

运行：`docker compose exec api pytest -q backend/tests -k 'candidate_list or candidates'`；`cd frontend && npx tsc -b && npx vitest run`。

预期：后端筛选去重，前端类型检查和现有测试通过。

### 任务 4：重构面试管理四 Tab 和 HR 操作

**文件：**
- 修改：`frontend/src/api/interviews.ts`
- 修改：`frontend/src/api/assignments.ts`
- 修改：`frontend/src/pages/InterviewPage.tsx`
- 修改：必要时 `frontend/src/pages/JobDetailPage.tsx`
- 测试：`frontend/src/pages/InterviewPage.test.tsx` 或现有页面测试

- [ ] **步骤 1：编写失败测试**

验证看板使用 `interview_result` 分组；待面试行出现四个反馈动作；通过 Tab 显示 offer/hired 的招聘状态；通过行能执行发 Offer、入职、拒绝 Offer；取消面试不出现在候选人筛选选项。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd frontend && npx vitest run src/pages/InterviewPage.test.tsx`

预期：当前 `GROUP_MAP` 按 offer/rejected 映射，测试失败。

- [ ] **步骤 3：实现页面**

移除按 `Assignment.status` 推导面试通过/不通过的映射，改用 API 返回的 `interview_result` 和是否存在未反馈轮次。反馈动作调用独立结果接口；保留面试轮次、AI 总结。增加 Offer、标记入职、拒绝 Offer 操作并刷新 board。表格增加“面试结果”和“招聘状态”两列，确保状态含义不混淆。

- [ ] **步骤 4：运行测试确认通过**

运行：`cd frontend && npx vitest run && npx tsc -b`。

预期：页面行为测试、类型检查全部通过。

### 任务 5：收紧自然语言查询状态口径

**文件：**
- 修改：`backend/app/services/search/extractor.py`
- 修改：`backend/app/services/candidate_search.py`
- 修改：`backend/app/services/search/schema.py`
- 修改：`backend/app/services/search/cards.py`（仅当输出需要展示新状态）
- 测试：现有 search extractor/candidate search 测试，创建状态边界测试

- [ ] **步骤 1：编写失败测试**

覆盖默认查询排除 `rejected`、`offer_rejected`、`hired`、`closed_*`；明确“面试通过”“未履行面试”“取消面试”“拒绝 Offer”“已入职”可产生对应条件；普通成员不能查询 hired；“面试通过”不产生 offer/hired 条件。

- [ ] **步骤 2：运行测试确认失败**

运行：`docker compose exec api pytest -q backend/tests -k 'search'`

预期：当前只支持 `offer_rejected` 历史谓词，新增条件测试失败。

- [ ] **步骤 3：实现解析和检索条件**

扩展搜索结构化条件为 `interview_result`、`assignment_status`；更新系统提示和白名单校验。默认 scope 继续走角色 ACL，并在候选人检索 SQL 中排除终止 Assignment；显式状态才允许加入对应 EXISTS 谓词。hired 仅 admin/owner 放行。保持已有 `offer_rejected` 条件兼容并映射到统一 Assignment 状态条件。

- [ ] **步骤 4：运行测试确认通过**

运行：`docker compose exec api pytest -q backend/tests -k 'search'`。

预期：状态解析、ACL、默认排除和显式查询测试通过。

### 任务 6：全量验证和部署检查

**文件：**
- 不新增业务文件；仅根据测试结果修改前述文件

- [ ] **步骤 1：运行后端全量测试**

运行：`docker compose exec api pytest -q`。

预期：全量通过。

- [ ] **步骤 2：运行前端验证**

运行：`cd frontend && npx tsc -b && npx vitest run`。

预期：类型检查和测试通过。

- [ ] **步骤 3：构建并检查服务**

运行：`docker compose up -d --build api worker frontend`；`curl -fsS http://localhost:8000/health`；`curl -fsS http://localhost:3000/`。

预期：API 返回健康状态，前端返回 200，迁移已应用。

- [ ] **步骤 4：Playwright 验证业务路径**

登录测试账号，打开 `/interviews` 和 `/candidates`，确认四个 Tab、四个待面试反馈动作、Offer 结果动作和三个候选人面试筛选选项均可见，切换筛选后请求包含 `interview_result`。

- [ ] **步骤 5：检查最终 diff**

运行：`git diff --check`；`git status --short`。

预期：无空白错误，只有本功能相关文件被修改；不回滚工作区中原有修改。
