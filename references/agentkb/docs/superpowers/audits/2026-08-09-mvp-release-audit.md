# MVP 发布审查报告（进行中）

> **状态：** 审查进行中。截至 2026-08-09 已完成两轮修复并通过全量回归（后端 324 passed + ruff 全绿；前端 5 passed + build；迁移全链可逆；`docker compose config` 通过）。下表「已验证修复」项已关闭；B-2 第一阶段已验证修复、第二阶段待生产回填后独立发布；剩余 A-5、E-2/E-3/E-6 未关闭。

**审查设计：** `docs/superpowers/specs/2026-08-09-mvp-release-audit-design.md`

**审查基线：** main `f1fda5f`，审查 worktree 分支 `mvp-audit`。

## 已执行验证

| 项目 | 结果 | 备注 |
|---|---|---|
| 后端 pytest | 324 passed | 审查前基线 270；累计新增 54 = 324（含 B-2 的 PII/IR 加密/回填测试） |
| ruff | 通过 | 本轮修复后全绿 |
| 前端 vitest | 5 passed | 保持不变 |
| 前端 production build | 通过 | 前端基线 5 passed + build（此前验证，本轮未实跑） |
| `git diff --check` | 通过 | 本轮验证通过 |
| 迁移可逆性 | 通过 | `upgrade head → downgrade base → upgrade head` 全链成功（含新增 B-6 迁移） |
| `docker compose config` | 通过 | 有无 `backend/.env` 均通过 |
| PostgreSQL | 可用 | `localhost:5432` |

## 已复现发现

| ID | 级别 | 风险域 | 文件/位置 | 复现证据 | 处理状态 |
|----|------|--------|-----------|----------|----------|
| A-1 | Critical | 权限隔离 | `api/assignments.py`、`api/interviews.py`、`api/resumes.py` | member 可从职位看板、候选指派历史、面试轮、ResumeIR 间接读取 hired 候选人的姓名、流程和 IR/PII | 已验证修复（含 resume run/IR/retry 负向回归） |
| A-2 | Important | 认证 | `api/deps.py:27`、`api/auth.py` | 正确签名但非法/缺失 `sub` 或 `jti` 的 JWT 导致 KeyError/ValueError 与 500 | 已验证修复 |
| A-3 | Important | 认证可用性 | `core/token_store.py:24`、`api/auth.py:71` | Redis 读取故障被转换为 refresh token 无效 401，而非服务不可用 | 已验证修复（503 契约） |
| A-4 | Important | 工作区隔离 | `services/assignment_service.py:76`、`api/assignments.py:61` | 跨 workspace candidate 指派返回 400，不符合统一 404 隔离契约 | 已验证修复 |
| A-5 | Important | 审计 | `services/audit.py`、各 API router | audit helper 存在，但敏感读取、权限拒绝、成员管理、面试操作和审计查询未完整实现 | 待裁决与修复 |
| B-1 | Critical | 简历格式 | `api/resumes.py:25`、`resume/pipeline.py` | 上传链接受并解析 PDF，与 PRD §9“PDF 严格拒收”冲突 | 已验证修复（上传入口拒收，pipeline 保留历史 run 兼容） |
| B-2 | Critical | PII/存储 | `resume/pii.py`、`pipeline.py`、`ingest.py` | 地址与自由文本姓名脱敏不完整；ResumeIR 原文持久化口径与 PRD IR 加密要求冲突 | 第一阶段已验证修复（保守地址/页首姓名出站脱敏、ResumeIR 新数据密文存储、历史回填命令与授权解密读取）；第二阶段待生产回填后独立发布 |
| B-3 | Important | 候选人生命周期 | `api/candidates.py` | deleted 候选人可立即 purge；物理文件不删除；进行中指派删除与恢复池重算缺失 | 已验证修复（30 天保留期、物理文件清理、进行中指派拒删、恢复池重算） |
| B-4 | Important | 字段修正 | `api/candidates.py`、`candidate_view.py` | override 路径/值未按 schema 校验；PII 字段可进入 JSON override 而非加密列 | 已验证修复（KNOWN_FIELDS+标量拒嵌套；phone/email 走加密列） |
| B-5 | Important | 重解析 | `api/resumes.py`、`resume/ingest.py` | retry 建新 Candidate，不追加原 CandidateRevision，override 不继承 | 裁决：与 F8 re-parse 已接受后续项重叠，retry 仅对失败 run 开放（无 candidate 可继承），不重复实现 |
| B-6 | Important | 幂等 | `api/resumes.py`、`models/parse_run.py` | upload/content hash 仅先查后写，无数据库唯一约束，存在并发重复 run 风险 | 已验证修复（部分唯一索引 NULLS NOT DISTINCT + 上传端 IntegrityError 兜底） |
| C-1 | Critical | 搜人历史条件 | `search/extractor.py`、`search/flow.py`、`search/statistics.py` | LLM `assignment_history=[{"event":"offer_rejected"}]` 被静默忽略，搜索和统计返回未过滤结果 | 已验证修复（搜人+统计集成测试） |
| C-2 | Important | 模型错误契约 | `api/search_chat.py` | `stream=false` 模型异常为 500；流式为通用 SSE `INTERNAL_ERROR` | 已验证修复（stream=false→502；stream=true→MODEL_ERROR） |
| D-1 | Critical | HC 并发 | `services/assignment_service.py` | 两个 session 使用陈旧 interviewing Assignment 同时 offer，可让同一指派 `hc_reserved += 2` | 已验证修复（transition/hire 锁后重载 + 并发回归测试） |
| D-2 | Important | 职位状态机 | `assignment_service.py`、`job_service.py` | open 职位可转 `closed_by_job`；closed 职位可重开 | 已验证修复 |
| D-3 | Important | 多轮面试 | `interview_service.py` | 前一轮无完整 advance 反馈仍可创建下一轮 | 已验证修复 |
| E-1 | Critical | Compose 启动 | `docker-compose.yml:22` | 缺少 `backend/.env` 时 `docker compose config` 失败，阻断默认启动路径 | 已验证修复（env_file required:false + compose 内嵌默认） |
| E-2 | Critical | MVP 评测 | `docs/superpowers/specs/` | M3/M4 只有规格，缺 bundle、fixture、scorer、manifest 和 CI 门禁 | 发布验收阻塞，需单独交付 |
| E-3 | Critical | 前端核心链路 | `frontend/src/pages/CandidatesPage.tsx` | 无文件上传、简历解析任务/重试入口，F6 无 UI 闭环 | 待修复 |
| E-4 | Important | 迁移 | `backend/alembic/versions/` | `upgrade head → downgrade base → upgrade head` 复现 enum DuplicateObjectError | 已验证修复（4 处 downgrade 补 DROP TYPE；含新迁移全链可逆） |
| E-5 | Important | 运行部署 | `docker-compose.yml`、`Makefile`、`.env.example` | Redis 本地端口缺失、PostgreSQL 5432 不可配置、前端未纳入 Compose、固定示例密钥 | 已验证修复（端口 ${VAR:-default} 可配置；前端 Dockerfile+nginx 纳入 Compose） |
| E-6 | Important | UI 契约 | `CandidatesPage.tsx`、`JobDetailPage.tsx` | 无批量指派 UI；安排面试需用户手动执行“创建面试轮→状态流转”顺序 | 待修复 |

## 已验证修复（本轮，全量回归通过）

以下项已修复并通过全量回归（后端 324 passed / ruff 全绿 / 前端基线 5 passed + build（此前验证）/ 迁移全链可逆 / `git diff --check` 通过）：

- **A-1**：候选池可见性统一 `candidate_access.get_visible_candidate`，接入职位看板、指派历史（单条+批次指派/历史）、面试轮（安排/反馈/总结/列表）、resume run/IR/retry；member 读 hired 全路径 404。新增回归：`test_member_cannot_read_hired_resume_run_or_ir`。
- **A-2**：access/refresh JWT 非法 `sub`/缺失 `jti` 统一 401（不再 500）。
- **A-3**：Redis 故障经 `TokenStoreUnavailable` 转为 503；新增 `test_refresh_token_store_unavailable_returns_503`。
- **A-4**：跨 workspace 候选人指派单条 404、批次逐项报错；新增负向测试。
- **B-1**：上传入口拒收 pdf（from-file 明确提示转换），`ALLOWED_FORMATS`/`ALLOWED_CONTENT_TYPES` 移除 pdf；pipeline 保留历史 run 兼容。
- **B-2（第一阶段）**：保守地址/页首姓名出站脱敏（仅标签式姓名与明确地址形态，不误伤公司/项目/技能）；ResumeIR 新数据密文存储（`content_enc`，读路径优先解密、迁移窗口回退明文）；历史回填命令（可重试、分批、失败中止）与授权解密读取（受控 500 不泄露密文/错误细节）。
- **B-3**：purge 需 30 天保留期结束；purge 删除物理文件；有进行中指派拒绝删除；restore 重算池。新增 4 个测试。
- **B-4**：override 路径按 `KNOWN_FIELDS` 校验、标量禁嵌套、数组子路径允许；phone/email 修正写入加密列与 hash，不进 JSON override。
- **B-6**：`parse_runs` 增加 `(workspace_id, file_hash, template_version, source_channel)` 部分唯一索引（`NULLS NOT DISTINCT`，排除 failed/dead_letter 以兼容 retry 复制 hash）；上传端捕获 IntegrityError 后回滚复用既有 run。
- **C-1**：`assignment_history` 谓词接入 search/statistics SQL（EXISTS offer_rejected），搜人与统计均有集成回归。
- **C-2**：`stream=false` 模型异常 502；`stream=true` SSE 区分 `MODEL_ERROR` 与 `INTERNAL_ERROR`。
- **D-1**：`transition`/`hire` 锁后重载 assignment 并二次校验状态；两个并发回归测试验证 `hc_reserved`/`hc_filled` 不重复计数。
- **D-2/D-3**：职位状态机与多轮面试闸门全量回归通过。
- **E-1**：`docker compose config` 在有无 `.env` 下均通过。
- **E-4**：4 个迁移 downgrade 补 `DROP TYPE`；`upgrade head → downgrade base → upgrade head` 全链可逆（含新增 B-6 迁移）。
- **E-5**：db/redis/api/worker/frontend 端口与 DB 口令均可通过环境变量配置；前端新增 Dockerfile + nginx（`/api` 反代 api、SPA 回退）。

## 已接受边界与待裁决项

- 面试反馈并发 last-write-wins：P8 台账已接受，后续可改为 revision/If-Match。
- statistics 年限分布按原始值桶：冻结 M4 fixture 时必须保持一致。
- 多轮统计追问：P9 台账已接受，当前为单轮统计意图。
- **B-5**：与 deviation-log 已接受后续项「F8 re-parse」重叠——retry 仅对 failed/dead_letter run 开放，此类 run 在 pipeline 失败点（ingest 之前）从不产生 candidate/revision，故无「追加 revision / 继承 override」对象；完整「重新解析保留人工修正值」语义留待 F8 re-parse 交付。
- **B-2（第二阶段）**：第一阶段已验证修复（保守地址/页首姓名出站脱敏、ResumeIR 新数据密文存储、历史回填命令与授权解密读取）。第二阶段待生产回填完成后独立发布：删除 `resume_irs.content` 明文字段并将 `content_enc` 设为 NOT NULL；不将 B-2 标记为最终关闭，直到生产回填校验与第二阶段 migration 完成。第二阶段 migration 不得与第一阶段合并提交或作为同一次 `alembic upgrade head` 部署。
- **B-2（第一阶段 migration downgrade 不可逆）**：第一阶段 upgrade 后写路径只写 `content_enc`（`content` 为 NULL），故第一阶段 migration 的 downgrade（`content` 改回 `NOT NULL`）在新数据存在时无法成功。属渐进迁移固有局限：回滚窗口仅保证「无 `content IS NULL` 新数据」或「明文读取历史数据」阶段有效；生产回滚需先确认无 `content IS NULL` 记录、或完成第二阶段后再回滚。
- **A-5（审计完整性）**：`audit.py` helper 已存在，敏感读取/权限拒绝/成员管理/面试操作/审计查询端点待裁决补齐范围后实现。

## MVP 验收状态（阶段性）

| 范围 | 状态 | 依据 |
|------|------|------|
| P0 功能代码 | 未通过发布审查 | 剩余 B-2 第二阶段（生产回填后独立发布）、E-2（M3/M4 评测）、E-3（前端核心链路）、E-6（UI 契约）、A-5（审计完整性）未关闭 |
| 后端自动化回归 | 通过 | 324 passed（审查前基线 270；累计新增 54 = 324）+ ruff 全绿 |
| 前端构建与单元测试 | 通过 | 5 passed + production build |
| M3 解析量化验收 | 未执行 | 无冻结数据集、scorer、manifest、真实模型配置 |
| M4 搜人与统计量化验收 | 未执行 | 无冻结数据集、scorer、fixture、CI 门禁 |
| MVP 发布结论 | 不可发布 | E-2 M3/M4 硬门槛未执行；B-2 第二阶段（明文删除）未发布 |

## 下一步

1. B-2 第二阶段：生产运行第一阶段代码并成功执行回填后，校验 `content IS NOT NULL AND content_enc IS NULL` 计数为 0 且完成一次解密抽样验证后，独立创建并发布第二阶段 migration（删除 `content`、`content_enc` NOT NULL）。
2. E-3/E-6 前端核心链路：简历上传/解析任务/重试入口、批量指派 UI、面试安排引导。
3. A-5 审计完整性：裁决敏感读取/权限拒绝/成员管理/面试操作/审计查询端点范围。
4. 冻结并实现 M3/M4 评测 bundle 后，更新本报告为最终发布审查结论。
