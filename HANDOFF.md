# MaxKB 人事招聘工作台 · 项目交接与开发提示词

> 本文件是给新开发平台/AI 助手的项目状态提示词。请先完整阅读本文件，再按需阅读 docs/PRD.md、docs/superpowers/ 下的规格与验收文档。

## 0. 一句话定位

在精简版 MaxKB v2（Django + DRF + Vue3）内核内嵌的多租户人事招聘工作台（ATS），业务全部在 `apps/hr`，已完成基础闭环、简历解析/检索、面试 Offer 状态机、AI 搜人、异步化、简历合并查重，以及「A 阶段生产基础补齐」（流程模型、访问控制与审计、数据生命周期）。

## 1. 技术栈与关键约束

| 项 | 内容 |
|---|---|
| 后端 | Python 3.11 / Django 5.2 / DRF / PostgreSQL 16(pgvector) / Redis / Celery（celery-once 防重） |
| 前端 | Vue 3 / Vite / Element Plus（ui/ 目录，admin 与 chat 两个 SPA） |
| 依赖 | uv（`uv sync --locked`），`uv.lock` 已入库 |
| 数据库/缓存 | docker：`maxkb-slim-pg`（postgres/maxkb-test）、`maxkb-slim-redis`（127.0.0.1:6379） |
| 包管理 | 后端 `uv`；前端 `pnpm`（ui/） |
| 代码风格 | ruff（line-length 120）、vue-tsc；提交用中文 Conventional Commits |

### 1.1 运行测试（关键！本机无 config.yml）

```bash
export MAXKB_CONFIG_TYPE=ENV \
  MAXKB_DB_NAME=maxkb MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
  MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
  MAXKB_DB_ENGINE=django.db.backends.postgresql MAXKB_DB_MAX_OVERFLOW=10 \
  MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_PASSWORD= \
  MAXKB_REDIS_DB=0 MAXKB_REDIS_MAX_CONNECTIONS=10

uv run python apps/manage.py test hr.tests --keepdb            # HR 全量
uv run python apps/manage.py test hr.tests application.tests knowledge.tests models_provider.tests ops.tests --keepdb  # 四 app + ops 全量
uv run python apps/manage.py makemigrations --check --dry-run  # 迁移漂移检查
uv run python apps/manage.py migrate --check                   # 未应用迁移检查
uv run ruff check apps/hr/
```

注意：`--keepdb` 首次跑可能因测试库缺最新迁移报瞬态错误，复跑即通过；不要据此误判代码缺陷。若测试报「source database maxkb is being accessed by other users」，说明测试库需要重建：`DROP DATABASE test_maxkb;` 后重跑（见第 5.1 节与提交 `fe42c65`）。

### 1.2 前端验证

```bash
cd ui
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build >/dev/null 2>&1 && echo ADMIN_OK
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat >/dev/null 2>&1 && echo CHAT_OK
```

## 2. 权威文档（按优先级）

| 文档 | 用途 |
|---|---|
| `docs/PRD.md` | 产品基线：定位、业务对象与状态机、权限、上线门槛、交付状态（第 9 节）、路线 |
| `docs/superpowers/specs/2026-08-14-hr-process-model-design.md` | A2 流程模型（职位状态/关联字段/状态迁移矩阵） |
| `docs/superpowers/specs/2026-08-14-hr-access-audit-design.md` | A3 访问控制与审计 |
| `docs/superpowers/specs/2026-08-14-hr-lifecycle-design.md` | A4 数据生命周期（删除匿名化/TTL/导出） |
| `docs/superpowers/audits/2026-08-14-hr-production-baseline.md` | A 阶段验收基线 + 部署验证项清单 |
| `README-hr.md` | 各期验收记录（一期到 A 阶段，含测试数演进） |
| `docs/superpowers/specs/2026-08-13-*.md` | 二至七期规格（简历/搜索匹配/AI/异步/合并） |

## 3. 已完成（当前测试基线：四 app + ops 240/240 PASS，HR 224）

### 3.1 PRD 七期（基础能力）

| 期 | 内容 | 验收 |
|---|---|---|
| 一 | 候选人/职位/指派基础闭环、工作区隔离 | 23 |
| 二 | 简历上传、docx/txt 规则解析、内容哈希去重、检索 | 31 |
| 三 | 组合搜索（多技能 AND/学历/年限区间）、职位匹配建议 | 39 |
| 四 | 状态机扩展（面试中/Offer/已入职）、面试轮次与反馈 | 47 |
| 五 | 工作区 LLM 配置、自然语言搜人、职位技能抽取 | 76 |
| 六 | Celery 异步简历解析（QueueOnce）、批量状态查询 | 86 |
| 七 | 简历下载/原文查看、手机号/邮箱查重、候选人合并 | 107 |

### 3.2 A 阶段（生产基础补齐，2026-08-14，14 个提交 b5c518d..520d288）

- **A1 流程口径**：归档拦截与 HC 统计覆盖全部进行中状态；候选人详情入口
- **A2 流程模型**：职位 `DRAFT/ON_HOLD/CLOSED`（close_reason）+owner；关联 `relation_type/channel/applied_at/owner_id/termination_reason/is_reapply` + `WITHDRAWN` 状态；服务端强制状态迁移矩阵（规格中有迁移表）；关闭职位批量收尾（PUT /jobs/{id}/close）；重新投递自动标记；误拒绝仅管理员恢复（REJECTED→PENDING_SCREEN）
- **A3 访问控制与审计**：`HrAccess`（VIEWER/OPERATOR/ADMIN 显式授权）、`hr_access_required`/`hr_admin_required` 装饰器、VIEWER 联系方式脱敏、`HrAuditLog` 操作审计（查看/创建/流转/简历/合并/导出/授权/越权拒绝）、人事成员与审计日志页面
- **A4 数据生命周期**：候选人合规元数据（source_type/source_detail/collected_at/consent_status/consent_version/contact_preference）；删除匿名化（DELETED 终态、PII 清空、简历联动删除，进行中/HIRED 拒绝）；未关联简历 30 天 TTL 每日 Celery 任务（`cleanup_orphan_resumes`，beat 注册在 task/resume.py 的 worker_ready 信号幂等创建（勿放回 apps.py ready，见 fe42c65））；受控白名单 CSV 导出（不含联系方式、公式注入转义）
- **A5 验收**：227/227 PASS；部署验证项已列出（见第 5 节）

### 3.3 关键实现模式（新功能必须遵循）

- **工作区隔离**：服务层每类资源按 `workspace_id` 过滤；跨工作区一律 404（不泄露存在性）；`GET /candidates/{id}` 对 DELETED 行限 ADMIN
- **权限**：HR 视图用 `@hr_access_required` / `@hr_admin_required`（views/permissions.py）；服务层 `_require_manage()` 等价 ADMIN；未授权写 ACCESS_DENIED 审计
- **状态机**：服务端是唯一权威（`_ALLOWED_TRANSITIONS` 矩阵）；终态必填终止原因；非法流转 400 含当前/目标状态
- **审计**：`write_audit_log(workspace_id, user_id, action, object_type, object_id, detail=...)`（services/audit.py）；敏感操作必须埋点
- **脱敏**：VIEWER 角色 phone `138****5678`、email `ab***@example.com`（_masked_phone/_masked_email）
- **并发**：合并/关闭职位/建关联用 `select_for_update` 固定行锁顺序（primary 先于 secondary）；锁内重查校验避免 TOCTOU
- **路由顺序教训**：`check-duplicate` 等静态段必须放在 `<str:xxx>` 动态段之前，否则被吞
- **表单输入**：枚举字段服务端校验 400；UUID 参数用 `_owner_id` 类校验器，避免 500

## 4. 审查发现并已修复的问题（避免重蹈）

- merge 冲突检查 TOCTOU → 事务 + 行锁
- saveCandidate 双提防护 promise 链未贯通 → `.then` 全分支 return，finally 覆盖保存完成
- owner_id 非法 UUID → 500（应 400）
- edit_job 绕过关闭专用语义（CLOSED 不带原因、CLOSED→OPEN）
- CSV 公式注入（= + - @ 前缀转义）
- DELETED 终态可被 edit/merge/archive 复活 → 三处 400 拒绝

## 5. 下一步（按优先级）

### 5.1 部署环境验证（A 阶段关闭前提，处理真实 PII 前必须完成）

- Celery worker+beat 真实调度：**heartbeat.py 硬编码 `/opt/maxkb-app/tmp`** → 已修复（2026-08-15）：探针目录改为 `MAXKB_WORKER_TMP` 环境变量覆盖、默认值不变（向后兼容）；新增 `apps/ops/tests.py` 4 用例，全量 231/231。本机起 worker 时 export `MAXKB_WORKER_TMP=$HOME/maxkb-tmp` 即可。TTL 清理 beat 任务（`hr-cleanup-orphan-resumes`）在 `apps/hr/task/resume.py` 的 `worker_ready` 信号中注册（勿改回 apps.py ready——那会在应用加载时访问数据库，导致测试库模板克隆被连接占用而失败，见提交 `fe42c65`）
- 对象存储私有化（当前简历在本地 `data/resume/`）
- TLS、数据库/备份静态加密、密钥管理
- 日志/监控脱敏人工检查
- 备份自然过期、租户注销与数据返还/删除流程

### 5.2 B 阶段：招聘协作与 Offer 交接（PRD 9.2）

| 项 | 内容 |
|---|---|
| 完整面试协作 | 面试官最小可见、反馈截止、决策记录（当前面试官仅为文本字段） |
| Offer 工件 | 独立实体：版本、审批、金额/币种、发送/接受/拒绝/撤回、附件权限（当前 OFFER 仅是状态） |
| 入职交接 | Offer 接受后向 HRIS/OA/人工清单幂等交接（可重试、不重复建员工） |
| 批量导入 | CSV 导入 + 失败/疑似重复报告 |

### 5.3 C 阶段：语义检索与智能优化

Embedding 语义召回、可解释匹配、人工反馈、索引与候选人生命周期同步、试点标注集 Top-K 对比。知识库/Embedding 语义检索当前明确未交付（PRD 第 9.1 节）。

## 6. 已知限制与口径

- 面试官是文本字段（非用户外键）；负责人存 user_id（UUID）未建外键
- 恢复误拒绝记录到 note（`[restore] <原因>`），未建独立字段
- 导出为固定白名单（不含联系方式）；批量导入未做
- TTL 每日调度，清理延迟最多约 24h
- 候选人「更正请求」由编辑+审计承接，无独立审批流
- 未关联简历允许存在（TTL 兜底）；`ResumeFile.candidate` 为 SET_NULL
- PRD 明确：`HIRED` 后不得新建职位关联；仅 REJECTED/WITHDRAWN/CLOSED 可重新投递

## 7. 提交流程与账本

- 每期：docs 规格提交 → docs 实现计划提交 → 实现（TDD）→ 全量验收 → 审查 → 修复
- 测试数演进：23→31→39→47→76→86→107→141→183→207→215（HR）→227（四 app）→231（四 app + ops 4，2026-08-15）→240（+候选恢复 9，2026-08-15）
- 规格/计划/验收文档路径规范：`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`、`docs/superpowers/plans/`、`docs/superpowers/audits/YYYY-MM-DD-<topic>-baseline.md`
- 提交信息：`feat(人事)/fix(人事)/docs(人事)/test(人事): 中文描述`

## 8. 文档审计结论（2026-08-15，未修复仅记录）

> 打包前对全部文档做了与代码事实的对照审计。以下问题**未修复**，仅记录备查。新平台接手后按此清单处理，处理前以「代码 + A 阶段规格 + 08-14 验收基线」为权威，不要以被标注的文档为准。

### 8.1 会误导的事实错误（建议优先处理）

| 文档 | 问题 |
|---|---|
| `docs/PRD.md` §9.1「当前实现边界」表 | 停留在 A 阶段前快照：「职位仅 OPEN/CLOSED」「关联无 WITHDRAWN/负责人」「权限复用工作区成员」「无审计」等，全部已被 A2/A3/A4 交付推翻；而 PRD 头部声明「以第 9 节为准」 |
| `docs/PRD.md` §4.1 与 §8 | 「建档至少姓名+一种联系方式」「服务端必须校验联系方式」规则从未实现（代码仅必填 name），未标注为未达成 |
| `docs/PRD.md` §7 审计门槛 | 「请求追踪标识」未实现（HrAuditLog 无 trace 字段），缺口未标注 |
| `docs/superpowers/specs/2026-08-13-hr-resume-async-design.md` §2.7 | 断言「sha256 唯一约束未在模型层实施」——事实错误（迁移 0003 已有 DB 约束，并发重复实为 IntegrityError 未捕获 → 500） |
| `docs/superpowers/specs/2026-08-14-hr-lifecycle-design.md` API 表 | 「编辑候选人 OPERATOR/ADMIN」与代码实际（仅 ADMIN）及 A3 矩阵矛盾 |
| `README.md`、`README_CN.md`、`CLAUDE.md` | 大量宣称已删除能力：工作流、MCP、函数库、多模态、本地模型（CLAUDE.md 约 12 处：`dev local_model` 命令报错、双 settings 描述、flow 引擎、sandbox 运行时、多供应商列表等）；README 宣称「workflows / MCP tool-use」 |

### 8.2 建议修改（可后置）

| 文档 | 问题 |
|---|---|
| `HANDOFF.md` §7 | 测试数演进链口径混用：23→107 为四 app 口径、141→215 为 HR 单 app 口径，未标注切换且漏 99；全量应表述为「四 app 227 = HR 215 + 内核 12」 |
| `README-hr.md` 第 76 行 | 「复用当前工作区认证与管理员权限」已过时（A3 后为 HR 显式授权） |
| `docs/PRD.md` §6 | 「AI 复用工作区管理端权限、显式授权属 A 阶段门槛」已过时（A3 已落地） |
| `docs/superpowers/specs/2026-08-14-hr-process-model-design.md` API 表 | `GET /assignments` 未实现（列表能力由 job/candidate 详情承载） |
| `CONTRIBUTING.md`、`SECURITY.md` | 仍指向上游 GitHub 链接，与本 fork 流程不符 |
| `docs/superpowers/audits/2026-08-14-hr-production-baseline.md` | 「分支 main」应为 v2 |

### 8.3 真实功能缺口（文档宣称但未实现，非文档问题）

| 缺口 | 说明 |
|---|---|
| **候选人恢复（ARCHIVED→ACTIVE）** | **已修复（2026-08-15）**：新增 `PUT /candidates/{id}/restore`（ADMIN，`hr_admin_required` + `_require_manage` 双层校验）、`restore_candidate` 服务方法（DELETED/非 ARCHIVED 拒绝 400）、`RESTORE` 审计（object_type=CANDIDATE）、前端列表/详情恢复按钮；9 个新测试，全量 240/240（见规格 `docs/superpowers/specs/2026-08-15-hr-candidate-restore-design.md`）。RESTORE 审计动作现同时用于指派误拒绝恢复（ASSIGNMENT）与候选人恢复（CANDIDATE） |

### 8.4 历史阶段记录（非错误，可保留）

一期至五期规格中的「状态只覆盖筛选阶段」「不新增审计表」「同步解析」「工作区成员权限」等，是当时正确、被后续阶段明确修订的决策记录；四期取舍「不引入审计表」已被 A3 推翻。判断优先级时以 §2 文档排序为准。
