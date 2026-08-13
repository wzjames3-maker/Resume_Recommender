# MVP 发布审查执行计划

> **面向 AI 代理的工作者：** 本计划用于审查与必要修复；每个风险域独立执行，Critical/Important 发现必须补回归测试并提交，Minor 只记录。

**目标：** 按 `2026-08-09-mvp-release-audit-design.md` 对 main 全项目实施发布审查，修复可复现的 Critical/Important 缺陷，并给出 MVP 功能与量化验收状态。

**架构：** 审查按五个风险域分批进行：身份隔离、导入解析安全、搜人与模型、招聘流程一致性、API/前端/迁移部署。每域先静态阅读与规格对照，再运行针对性测试或临时复现；代码修复保持最小范围，最后做全量回归。

**技术栈：** FastAPI、SQLAlchemy async、PostgreSQL/pgvector、Redis、Celery、React/Vite、pytest、ruff、vitest、Alembic、Docker Compose。

---

## 计划审查约束

- 审查基线：当前 worktree `f1fda5f`，对应 main 的 MVP 发布审查设计。
- 临时复现脚本只写 `/tmp/opencode/mvp-audit/`，不纳入 git。
- 数据库测试使用现有 PostgreSQL；测试前确认 `localhost:5432` 可用，不自动删除用户数据。
- 只在发现可复现 Critical/Important 时改应用代码；不得为了“看起来完整”添加推测性功能。
- 每项修复都要有最小回归测试，提交信息包含风险域与编号。

## 文件范围

**静态审查：**
- `backend/app/api/`、`backend/app/services/`、`backend/app/models/`、`backend/app/core/`
- `backend/alembic/versions/`、`backend/tests/`
- `frontend/src/api/`、`frontend/src/pages/`、`frontend/src/stores/`
- `docker-compose.yml`、`Makefile`、`backend/.env.example`
- `docs/PRD.md`、`docs/superpowers/specs/`、`docs/superpowers/deviation-log.md`

**可能修改：** 仅发现并确认 Critical/Important 后涉及的应用文件、回归测试、台账；新增最终审查报告 `docs/superpowers/audits/2026-08-09-mvp-release-audit.md`。

---

### 任务 1：建立基线与审查台账

- [ ] **步骤 1：确认 worktree 与主线状态**

运行：

```bash
git status --short
git log --oneline -12
git diff --check
```

预期：工作区干净；记录当前 HEAD，不修改 main。

- [ ] **步骤 2：运行基线验证**

运行：

```bash
export MODEL_KEY_ENC_KEY="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
export JWT_SECRET="deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/agentkb"
/home/wzjames/toC/maxkb-replica/.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests -q
/home/wzjames/toC/maxkb-replica/.worktrees/p2-resume-parsing/.venv/bin/ruff check backend/app backend/tests
cd frontend && npx vitest run && npm run build
```

预期：记录基线测试数；若失败，区分环境阻塞与已有失败，不将其归因于审查改动。

- [ ] **步骤 3：建立审查台账骨架**

创建最终报告时使用以下字段记录每项：

```markdown
| ID | 级别 | 风险域 | 文件/行号 | 复现证据 | 影响 | 处理 |
|----|------|--------|-----------|----------|------|------|
```

提交：

```bash
git add docs/superpowers/plans/2026-08-09-mvp-release-audit.md
git commit -m "docs: 添加 MVP 发布审查执行计划"
```

---

### 任务 2：域 A 身份、权限与工作区隔离

**审查规格：** 设计文档“风险域 A”。

- [ ] **步骤 1：静态核验认证和成员权限**

检查：

```bash
rg -n "get_current_user|WorkspaceMember|role|HTTPException\(404|refresh|revoke|token" backend/app/api backend/app/services backend/app/core
```

逐项对照 PRD F9：登录/刷新/撤销、owner 继承 admin、member 上传与职位创建、职位管理权限、跨 workspace 预检、hired 池可见性。

- [ ] **步骤 2：运行负向访问验证**

运行已有权限测试，并针对缺口在 `/tmp/opencode/mvp-audit/domain-a/` 写临时 httpx 脚本，至少覆盖：

```python
assert cross_workspace_candidate_response.status_code == 404
assert cross_workspace_job_response.status_code == 404
assert member_hired_list_response.status_code in (403, 404)
assert refresh_after_revoke_response.status_code in (401, 404)
```

- [ ] **步骤 3：修复并回归**

若发现 Critical/Important：修改最小代码，补到对应 `backend/tests/test_*api.py`，运行相关测试、ruff、`git diff --check`，提交：

```bash
git add backend/app backend/tests
git commit -m "fix: 修复 MVP 权限隔离审查发现（A-Rx）"
```

---

### 任务 3：域 B 导入、解析与候选人数据安全

- [ ] **步骤 1：静态核验上传、PII、幂等与生命周期**

检查：

```bash
rg -n "content_type|file_size|sha256|hash|retry|checkpoint|encrypt_secret|decrypt_secret|phone|email|deleted|purged|override|merge" backend/app/services backend/app/api backend/app/models
```

对照 MVP 矩阵验证文件签名/大小/压缩/XML限制、批量无半批提交、内容与 upload 幂等、重试 checkpoint、出站脱敏、查重合并、override、软删除恢复与索引清理。

- [ ] **步骤 2：运行安全和幂等回归**

运行：

```bash
/home/wzjames/toC/maxkb-replica/.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_importers.py backend/tests/test_ingest.py backend/tests/test_pii.py backend/tests/test_candidates_api.py backend/tests/test_candidate_merge.py backend/tests/test_candidate_view.py -q
```

对未覆盖边界用临时测试复现：恶意扩展名/签名、超限 JSON/CSV、重复内容、失败重试、deleted 检索与 PII 审计泄露。

- [ ] **步骤 3：修复并回归**

Critical/Important 修复补回归测试，按域 B 编号提交；Minor 写入审查报告并标注是否阻塞发布。

---

### 任务 4：域 C 搜人、统计与模型调用

- [ ] **步骤 1：静态核验解析、检索、统计与出站边界**

检查：

```bash
rg -n "validate_|build_condition_filter|ALLOWED_SCOPES|pool_scope|search_tsv|rerank|ModelCallError|outbound|chat_json|statistics|StreamingResponse" backend/app/services backend/app/api
```

对照搜人评测 §3.1-§3.8 与 F11：非法 LLM 输出 fail-closed、profile JOIN、requested_count、follow-up context、统计 count/distribution、ACL、模型失败降级、审计脱敏、SSE/非流式一致。

- [ ] **步骤 2：运行检索和统计回归**

运行：

```bash
/home/wzjames/toC/maxkb-replica/.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_search*.py backend/tests/test_job_search_flow.py backend/tests/test_model_client*.py -q
```

临时复现：非法 AST 类型、恶意统计维度、跨池计数、rerank/LLM 失败、统计审计 payload、SSE 与非流式响应。

- [ ] **步骤 3：修复并回归**

Critical/Important 修复必须覆盖搜索和统计两条路径；运行域 C 全套测试后提交。

---

### 任务 5：域 D 招聘流程与数据一致性

- [ ] **步骤 1：静态核验职位、指派、池聚合、面试闸门**

检查：

```bash
rg -n "for_update|hc_reserved|hc_filled|AssignmentStatus|transition|recompute|hire|InterviewRound|recommend|feedback|overdue" backend/app/services backend/app/api backend/app/models
```

逐项对照 F10/F13/F14/F15：HC 并发、状态矩阵、终态、候选人锁顺序、hired 聚合、关闭职位、面试轮顺序、评分/评语闸门、成员校验、反馈历史与 48h 待办。

- [ ] **步骤 2：运行招聘流程回归**

运行：

```bash
/home/wzjames/toC/maxkb-replica/.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_job*.py backend/tests/test_assignment*.py backend/tests/test_interview*.py -q
```

对 HC 超卖、并发流转、非法终态重开、offer 绕过反馈、跨 workspace 面试操作写临时复现。

- [ ] **步骤 3：修复并回归**

按最小范围修复并补回归测试；明确记录任何已接受的并发语义或迁移限制。

---

### 任务 6：域 E API、前端、迁移与运行部署

- [ ] **步骤 1：核验 API/前端契约**

检查：

```bash
rg -n "fetchWithRefresh|searchChat|interview|assignment|job|candidate|statistics|conversation" frontend/src/api frontend/src/pages backend/app/api
```

逐项验证主要 P0 UI 路径：注册/登录、工作区、候选人列表/详情/修正、职位、指派、面试反馈、搜人/统计；重点检查响应字段、404/403、SSE 事件和空/错误状态。

- [ ] **步骤 2：验证迁移与容器**

运行：

```bash
docker compose config --quiet
export MODEL_KEY_ENC_KEY="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
export JWT_SECRET="deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/agentkb"
/home/wzjames/toC/maxkb-replica/.worktrees/p2-resume-parsing/.venv/bin/alembic current
```

如环境允许，在临时数据库执行 upgrade head；记录 Redis 端口、`.env` 要求、API/worker 启动依赖与当前运行阻塞。

- [ ] **步骤 3：运行前端和契约回归**

运行：

```bash
cd frontend && npx vitest run && npm run build
```

---

### 任务 7：MVP 验收回填与最终报告

- [ ] **步骤 1：全量验证**

运行：

```bash
export MODEL_KEY_ENC_KEY="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
export JWT_SECRET="deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/agentkb"
/home/wzjames/toC/maxkb-replica/.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests -q
/home/wzjames/toC/maxkb-replica/.worktrees/p2-resume-parsing/.venv/bin/ruff check backend/app backend/tests
cd frontend && npx vitest run && npm run build
git diff --check
```

- [ ] **步骤 2：生成最终审查报告**

创建 `docs/superpowers/audits/2026-08-09-mvp-release-audit.md`，包含：

```markdown
# MVP 发布审查报告
## 执行摘要
## Critical / Important 发现与修复
## Minor 与已接受边界
## MVP 验收矩阵回填
## M3/M4 量化评测阻塞项
## 验证证据
## 发布结论
```

- [ ] **步骤 3：提交审查资料**

```bash
git add docs/superpowers/audits docs/superpowers/deviation-log.md
git commit -m "docs: 记录 MVP 发布审查结果"
```

---

## 自检

- 规格中的 A-E 五个风险域分别对应任务 2-6。
- MVP 验收回填、全量验证和最终报告对应任务 7。
- 没有要求预先知道审查发现的代码修改；只有复现后才产生修复提交。
- 环境阻塞与代码缺陷分开记录；真实模型/数据集不被 mock 结果替代。
- 当前计划只用于审查和必要修复，不扩大到 P1 功能或无关重构。
