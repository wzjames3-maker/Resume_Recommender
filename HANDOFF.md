# 项目交接（当前状态）

## 0. 一句话

MaxKB v2 精简内核 + `apps/hr` 人事招聘工作台。RAG 已交付；ATS 已迁移到传统 ATS 的 `Application + JobStage + StageHistory` 主链；Agent 的 D1/D2/D3 与 D4 工作台首版已实现，当前持续处理与总库/业务库多库模型的运行时兼容。

## 1. 必须读的文档

| 文档 | 内容 |
|---|---|
| `docs/PRD.md` | 产品基线 |
| `docs/ATS-STATE-MACHINE-V2.md` | 新 ATS 目标设计（当前最重要的重构依据） |
| `docs/ATS-OPENSOURCE-REFERENCE.md` | 传统 ATS 开源调研 |
| `docs/ATS-DESIGN-SPEC.md` | 当前代码事实，仅迁移对照 |
| `docs/PRD-AGENT-RAG.md` | Agent + RAG 设计 |
| `docs/RAG-V2-DESIGN.md` | 已交付简历 RAG 设计 |
| `docs/RESUME-DATABASES.md` | 总库、多业务库、成员关系和库内页面设计 |
| `docs/DEPLOYMENT.md` | 部署清单 |
| `docs/HR-FRONTEND-GUIDE.md` | 人事部前端使用流程指导（操作手册） |

## 2. 技术栈与运行

后端：Python 3.11 / Django 5.2 / DRF / PostgreSQL 16(pgvector) / Redis / Celery。
前端：Vue 3 / Vite / Element Plus，在 `ui/`。
包管理：后端 uv；前端 pnpm。

```bash
export MAXKB_CONFIG_TYPE=ENV \
  MAXKB_DB_NAME=maxkb MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
  MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
  MAXKB_DB_ENGINE=django.db.backends.postgresql MAXKB_DB_MAX_OVERFLOW=10 \
  MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_PASSWORD= \
  MAXKB_REDIS_DB=0 MAXKB_REDIS_MAX_CONNECTIONS=10

uv run python apps/manage.py test hr.tests application.tests knowledge.tests models_provider.tests ops.tests common.tests --keepdb
uv run python apps/manage.py makemigrations --check --dry-run
uv run python apps/manage.py migrate --check
uv run ruff check apps/hr
```

前端：

```bash
cd ui
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build
```

## 3. 关键决定

1. 旧 `references/agentkb/` 已删除，不作为参考。
2. 旧 ATS 固定状态机不修修补补，按传统 ATS 重构：
   - `JobStage`：每个职位可配置 Pipeline；
   - `Application`：候选人×职位流程对象；
   - `Application.status`：终态与阶段分离；
   - `ApplicationEvent`：不可变流程账本。
3. RAG 链路保持已交付形态，只允许增加可选 `candidate_id/document_ids/resume_database_ids` 限定召回范围；未传范围时保持原行为。
4. Agent 只有 Proposal 一个写出口；人工确认后调用 ATS 命令。
5. 测试 Key 不是安全问题，但正式环境必须使用环境变量注入正式 Key。

## 4. 下一步

- R1（基础模型与命令服务）、R2（Job 两阶段关闭 STRICT/BULK）、R3（Interview/Offer/Handoff 挂 Application + Offer 接受联动 HIRED）、R4（前端动态 Pipeline 看板）、R5（API 权限/幂等/终态矩阵测试）已完成，HR 全量 419 tests 通过。
- 新增：`POST/GET /hr/jobs/{job_id}/close(-preview)`、`/hr/applications/{id}/interviews|offers`；`search_resumes` 增加可选 `candidate_id/document_ids/resume_database_ids` 范围限定；存量 CandidateAssignment 迁移已内建为迁移 0025 的 RunPython 数据兜底（幂等锚点 ApplicationEvent(IMPORTED)），原 `import_legacy_assignments` 管理命令随重构移除。
- D1 Screening Agent 已完成：`hr_agent_run` / `hr_agent_proposal` 模型与 0022 迁移、
  `apps/hr/agents/` 包（Runner 固定顺序工具编排 + PII 上下文投影 + 服务端评分派生建议动作 + Proposal 审批）、
  Application 创建时 APPLY/REFERRAL 自动触发（celery-once 防重）、并发/速率护栏、LLM 失败降级 run=FAILED 业务零影响；
  API：`POST /hr/agents/SCREENING/run`、`POST /hr/proposals/{id}/accept|dismiss`、`GET /hr/applications/{id}/proposals`；
  审计新增 AGENT_RUN/AGENT_DECIDE（HrAuditLog 已补 trace_id）。Screening 当前支持 `resume_database_ids`，并按 `ResumeDatabaseMembership` 限定候选人证据文档。
- D2 已完成：企业知识库工具 search_knowledge（HrConfig.agent_knowledge_bases 白名单 + PII 掩码）、similar_jobs（SQL 相似 + HIRED 画像）、JD 起草 Agent（JD_DRAFT，propose DRAFT target=JOB，采纳仅写字段需 ADMIN）与 Interview Copilot（INTERVIEW_COPILOT，prepare 面试题 / feedback 评估草稿，仅本人面试官或 OPERATOR+ 触发）、AgentRunAPI 支持五类 Agent、job/interview proposals 列表、AI 设置页知识库白名单、职位 JD 草稿抽屉与我的面试 AI 助手；迁移 0023，HR 全量 486 tests 通过。
- D3 已完成：Sourcing 人才库激活（SOURCING，沉睡候选人池 + 硬条件核对 + 激活清单 DRAFT×JOB）、
  沟通草稿助手（COMMUNICATION_DRAFT，REJECT/PROGRESS/FAQ/OTHER 话术 + 企业话术库）、
  反馈闭环统计（GET /hr/agents/stats，agent_type × 动作 × 分数带采纳率，工作台采纳率卡片）、
  真实模型探针管理命令 `hr_agent_probe`（RUN_REAL_MODEL=1 + 环境变量凭据，验证 JSON 能力与 Screening 端到端）；
  迁移 0024，HR 全量 500 tests 通过。
- Agent 多库兼容修正（当前轮）：新增 `apps/hr/agents/scope.py`，Screening、Interview Copilot、Sourcing 支持可选 `resume_database_ids`；显式库范围校验 ACTIVE/工作区归属，候选人证据通过 `ResumeDatabaseMembership` 限定，运行账本记录范围，新增 `apps/hr/test_agent_scope.py` 回归测试。
- Agent 前端已完成业务流程内嵌版和 D4 工作台首版：职位页提供 Screening、JD、Sourcing、沟通草稿入口和 Proposal 操作，my-interviews 提供 Interview Copilot，dashboard/AI 设置提供统计与配置，Screening/Sourcing 支持 ACTIVE 简历库选择；`/hr/agents` 集中展示运行记录、工具轨迹、Token、失败重试、Proposal 收件箱和证据链。
- D1 评测标定基线已完成（2026-08-17，真实模型）：`import_resume_dataset`（数据集/train.json 300 份语料导入，
  预切片免 LLM 切片 + 幂等 + 同步向量化）、`eval_screening`（正/负画像配对 + 4 并发真实 Screening，
  报告 docs/screening-eval-2026-08-17.json 与 docs/SCREENING-EVAL-2026-08-17.md）；
  基线 200 例宽松一致率 72%（正 44% / 负 100%），未达 ≥80% 目标——诊断：泛技能职位构造 +
  flash-lite 保守评估（正样本误拒）、LLM 校验失败 13%；建议评测构造升级（完整 JD）与模型档位对比后再标定。
- 当前轮使用桌面 API 对项目数据集/train.json 直接复测切片：30/30 内容保真，29/30 LLM 路径，1/30 smart 规则兜底，29/30 非空行覆盖，0/30 PII 命中，31 次 LLM 调用；报告为 installer/dataset30_report.json。同时修复 installer/resume_splitter_dataset30.py 的 Django 初始化、项目数据集读取和旧 Label Studio 回退。
- 重构回归与迁移兜底（2026-08-17）已完成：全量回归（后端 482 tests OK：hr/application/knowledge/models_provider/ops/common；前端 vue-tsc + vite build admin/chat 均过；migrate --check 真实默认库过）；
  迁移 0025 加 RunPython 数据兜底（无 Pipeline 的 Job 建默认 JobStage、CandidateAssignment→Application 按状态映射、ApplicationEvent(IMPORTED) 幂等锚点、Interview/Offer/Handoff 的 assignment_id 回填、最后删表），
  已在真实开发库执行验证（7 存量指派 → 7 Application + 7 IMPORTED 事件 + 3 Job 补 Pipeline + 6 子对象回填，0 丢失）；
  关键点：本 schema 外键均为 DEFERRABLE INITIALLY DEFERRED，回填后须 SET CONSTRAINTS ALL IMMEDIATE 清空待处理触发事件，否则同事务 DROP CONSTRAINT 报 pending trigger events；
  另修复内核既有测试缺陷（application/tests.py 默认文件夹夹具 create→get_or_create）。
- D1 优化轮（screening-v2，2026-08-17）已完成并提交：评测构造升级（正样本职位由候选人单一代表角色渲染完整 JD，职责/技能同源 + 无技能重合回退首段职责）、
  Screening 提示词重标定（relevance/confidence 按实质语义支撑映射，禁因格式疑点压数值）、4 次退避重试 + JSON 修复一轮（FAILED 13%→1.5%）、
  HOLD 分带默认 60→48（screening-v2 操作点，可覆盖；48-59 疑似匹配改 HOLD 人工复核）、eval 陈旧运行恢复；
  同 seed 7 全量 200 例真实重测：宽松一致率 82.5%（正 65% / 负 100%，达成 ≥80%），严格一致率 55%（ADVANCE 12 例）；
  诊断：残留误拒为 flash-lite 数值标定（清晰匹配评 0-47 分，评论文本却明说一致），彻底解决需更强模型档位（当前账号仅有 flash-lite）；
  报告 docs/SCREENING-EVAL-2026-08-17b.md + JSON、全量 486 tests OK。
- 部署验证（PRD §8，2026-08-17）已完成：Celery worker+beat 真实调度（探针文件、`hr.task.agent` 任务注册、beat 19:00 派发→worker 执行）、
  对象存储私有读（匿名 403/签名 200）、备份加密+恢复演练+轮转（42M Salted__/pg_restore 637 条目）、日志 PII 脱敏复核（无真实泄露）、
  .env.example 600/默认 DEBUG=False、PG 连接加密补齐（MAXKB_DB_SSLMODE→OPTIONS sslmode）；本轮还修复探针目录自动创建并增加 Celery 注册测试；报告 docs/DEPLOYMENT-VERIFY-2026-08-17.md。
  租户注销/数据返还阶段 A、B1、B2、B3 已实现（见下条新增记录）；若未来接入外部租户平台，仅需让其 Workspace 删除事件调用本仓库的统一 callback。
- 租户注销/数据返还（设计稿阶段 A，2026-08-18）已完成并提交：新增 hr_offboard tombstone（0026 迁移，幂等锚点+留痕：执行人/时间/各表计数/导出包路径，注销后唯一保留的 HR 记录）、
  hr_offboard_workspace <workspace_id> [--dry-run|--force|--export <dir>|--user-id <uuid>] 命令（默认即审计+清理；dry-run 只统计；export 先出脱敏 JSON 数据返还包再清理；force 绕过活跃守卫：有 PENDING/RUNNING Agent 运行 / ACTIVE 申请 / 非 CLOSED 职位时拒绝）、
  清理顺序严格按「先子后父、先账本后配置」：简历语义索引 delete_resume_knowledge 批量删文档/段落/向量/知识库（含孤儿）→ 流程对象与级联子对象 → 职位/阶段 → 候选人 → 简历文件 → 配置/授权/审计/流转日志 → 存储对象缺失容忍；
  全程审计 EXPORT/DELETE 行随 hr_audit_log 一并清空，存证以 hr_offboard 为准；
  hr.tests 新增 HrOffboardCommandTests 7 例（全量归零/索引与存储清空/dry-run 与实际计数一致/幂等重入报已注销/跨工作区隔离/守卫拒绝/导出脱敏+路径留痕），HR 全量 440 tests OK + ruff 干净；
  已在真实开发库端到端验证：offboard-e2e 工作区 23 行/1 存储文件清零、7 段导出 JSON 脱敏（138****5678 / e2***@example.com）、二次执行报已注销不重删。
- 租户注销阶段 B1（2026-08-18）已完成：新增 `hr.services.offboarding` callback contract（preview/export/offboard），命令与 callback 共用无输出执行器；新增 HR ADMIN 范围内的 preview/export/purge Web API，POST 强制 `confirm_workspace_id`，可返回脱敏数据返还包；新增权限、跨工作区、导出不落库、确认、防误删与活跃守卫测试。当前精简内核没有统一 Workspace ORM/注销生命周期，因此 B2 仍需由实际内核生命周期调用该 callback，并补齐内核其它域与统一对象存储编排。
- 租户注销阶段 B2（2026-08-18）已完成：新增 `WorkspaceOffboard` 统一跨域 tombstone、`WorkspaceOffboardingService` 与 `workspace_offboard` 命令；编排 application/knowledge/model/权限/映射/日志/chat/HR，按资源 ID 精确清理内核文件，外层事务提交后统一回收 HR 对象存储；新增 Workspace ADMIN 系统 API 与 HR「租户注销」页面，支持预览、脱敏返还包、确认、force、事务失败回滚和幂等；system_manage 针对性回归与 staging-equivalent 演练通过，全量 backend 498 tests OK，vue-tsc/admin/chat build OK。
- 租户注销阶段 B3（2026-08-18）已完成：对象存储失败重试闭环；新增 `WorkspaceOffboard` 的 `storage_status`（`COMPLETED`/`STORAGE_PENDING`）、总尝试次数/最后错误/最后错误时间，新增 `WorkspaceOffboardStorageCleanup` 逐对象账本及迁移 0007/0008；失败不回滚跨域数据库删除，`python apps/manage.py workspace_offboard_storage_retry <workspace_id>` 可重试，管理 API `GET/POST /admin/api/workspace/{workspace_id}/offboarding/storage` 可查看失败对象并重新回收，注销页面已显示状态、失败 key、尝试次数和重试按钮；失败删除、客户端初始化失败、完成后重复 retry、API、双工作区 staging-equivalent 均有测试，system_manage 10 tests OK。S3 删除异常不再静默吞掉（兼容旧 HR 调用转换为 OSError）。
- 本轮 staging-equivalent 验收已完成：双工作区完整资源/权限/文件、preview、返还包敏感字段扫描、目标对象删除失败→`STORAGE_PENDING`→重试恢复、另一工作区不受影响；MinIO 匿名 403/目标删除/另一租户对象保留；加密备份解密恢复 637 entries；隔离 Redis DB15 worker 注册 `celery:hr_run_screening_agent`、探针和真实 cleanup task 均通过。真实 staging 与外部 Workspace 生命周期仍需平台侧演练。
- 简历多库与总库（2026-08-18）已完成：新增 ResumeDatabaseMembership 多对多关系和 0028 迁移；总库由服务端强制加入，业务库支持多选与归档，重复 SHA-256 简历跨库复用；候选人筛选、库统计和 RAG 全链路均按成员关系限界；前端改为 /hr/candidates 多库总览，点击库卡片进入 /hr/resumes/databases/:databaseId 库内候选人页面，库内上传和检索继承当前库；细节见 docs/RESUME-DATABASES.md。开发库验收：总库 261 份简历、261 位候选人、261 条总库成员关系；0028 已应用，vue-tsc、目标文件 ESLint、Vite production build 和 GUI HTTP 200 均通过。低层 ResumeFile.save 现在自动补齐总库和总库成员关系，未传 RAG 范围时保持原响应兼容。
- 数据库恢复与 D4 修复（2026-08-18）：PostgreSQL/Redis/MinIO 原 Docker 容器（maxkb-slim-pg / maxkb-slim-redis / maxkb-slim-minio）恢复启动，HR 全量 453 tests OK；修复 D4 工作台两处真实缺陷——运行详情证据链改为合并 Proposal payload（不再只看 output_json）、日期筛选纯日期结束时间解析（Django parse_datetime 对纯日期补零导致 end=True 失效）。工作台 6 例回归测试通过。
- Screening 真实评测复测（2026-08-18，数据库恢复后）：同 seed 7 全量 200 例，宽松一致率 82%（正 64% / 负 100%），严格一致率 82%（基线 v1 72%、screening-v2 82.5%）；报告 docs/SCREENING-EVAL-2026-08-18.md + logs/screening_eval_200_2026-08-18.json。评测构造与模型链路完整可复现。
- Agent 工作台完善（2026-08-18）：新增跨页汇总（list_runs 返回 summary：筛选范围内运行总数/各状态计数/Token/耗时，前端统计卡片改全局值并新增耗时展示）；Interview Copilot feedback 重试新增前端输入表单（原反馈未安全保留，重试必须重新提供反馈文本，与后端 retry_run 校验一致）；工作台 6 例回归测试通过，ruff/vue-tsc/eslint/Vite build 通过。
- Agent 工作台完善（本轮）：新增 workspace 隔离的证据段落 API（Paragraph → Document → ResumeFile 归属校验），工作台证据摘录可打开简历原文段落抽屉；新增 7 例回归测试覆盖原文返回、跨 workspace 404 和非法段落 ID。ruff/vue-tsc/eslint 已通过。
- Agent 工作台运行概览（本轮）：新增「运行概览」tab，复用 agent_feedback_stats 按 Agent 类型展示运行数/成功/失败/跳过、提案总数/已决/采纳率，概览、运行记录、Proposal 收件箱三页签齐备。
- 租户注销真实 staging 演练（2026-08-18）已完成：在真实开发库 + MinIO 上对 ws-dbg 端到端验证——dry-run 预览、活跃守卫拦截（有内核知识库需 --force）、force 注销、跨域清理（HR candidates/resumes/skills/memberships + 内核 knowledge/documents/paragraphs 归零）、脱敏返还包（无手机/邮箱泄露）、tombstone 留痕（COMPLETED/attempts=1）、存储逐对象账本 3 条、MinIO ws-dbg 对象 0 剩余、幂等重入报已注销；报告 docs/OFFBOARD-DRILL-2026-08-18.md。生产化前置验证完成，剩余为外部租户平台生命周期接入。
- HR 前端设计审查与整改（本轮，2026-08-18）：按审查清单全面整改——
  功能去重：职位展开行内嵌 Kanban 移除（改为候选人列表+前往 Pipeline 入口，拖拽/回退统一收口到独立 Pipeline 页并补回退原因收集）；候选人页「批量上传」与「批量导入」合并为「导入候选人」下拉；上传页/新建职位重复返回入口去重；
  过度设计：上传页移除「处理流程」说明块与重复的「本次上传」摘要；
  技术细节收敛：语义检索页默认只显示搜索框+库范围+检索，「模式/TopK/检索元信息/分数拆解」收进「高级选项」；
  层级调整：Pipeline 头部去掉无关上传/库入口，「查看候选人」从时间线移到详情顶部；候选人详情「系统与合规信息」8 个低价值字段折叠默认收起；工作台 Agent 采纳率卡默认折叠。
  vue-tsc、ESLint、Vite production build 全部通过。
- 面试管理模块打磨（本轮）：新增 HR 全局面试列表（InterviewListAPI / GET /hr/interviews，OPERATOR+），支持分页、按状态/候选人/职位/面试官关键词和逾期筛选，返回候选人/职位/轮次/面试官/日程/反馈截止与文本；新增 /hr/interviews 页面（筛选 + 表格 + 反馈抽屉），与「我的面试」（本人视角）互补。新增服务回归测试 1 例，工作台/面试模块共 8 例通过，ruff/vue-tsc/eslint 通过。
- HR 前端整体打磨（本轮）：新增人事部固定二级导航（工作台/Pipeline/简历库/职位/面试/Agent，管理员专属入口收进「更多」）；新增 HR 专属视觉基线和响应式样式，统一页面背景、卡片、表格、筛选栏、标题眉题、状态层级与移动端布局；工作台增加图标快捷入口、关键指标和逾期反馈统计；候选人/职位筛选增加重置，面试/Agent/Offer/交接页面统一操作头部与上下文入口。vue-tsc、ESLint、Vite production build 通过。
- HR 成员模型修复（本轮）：精简部署下内核 get_user_members 兜底排除 ADMIN 导致成员列表为空——负责人/面试官显示 UUID、/hr/access 空、面试官指派被「非工作区成员」拒绝。新增 hr.serializers.access.hr_members（内核成员为空时回退全部活跃用户，排除内置系统管理员），list_access/set_access 与面试官校验统一走该数据源；新增 GET /hr/members（任意 HR 成员可读）作为负责人/面试官下拉与姓名解析来源，jobs/create、jobs/index、candidates/index、candidates/detail 四个页面从内核 user_member 切到 HR 成员接口。新增回归测试 3 例（成员目录、非成员 403、内核空回退），HR 全量 444 + 全量 498 tests OK，ruff/vue-tsc/eslint/vite build 通过，GUI 职位编辑弹窗负责人已由 UUID 恢复为姓名。
- 前端弹窗遮挡修复（本轮）：职位编辑/关闭等 el-dialog 在 1366x768 及更小窗口下 footer（操作按钮）被切出视口且 body 不可滚动（Element Plus 弹窗无最大高度限制）。在 hr.scss 为 `.is-hr-main .el-dialog` 增加 flex 纵向布局 + `max-height: calc(100vh - 15vh - 48px)` + body 可滚动，footer 始终可见；大屏行为不变。playwright 实测 1366x768/1280x720 footer 可见可滚动、1600x900 无回归，vite build 通过。
- 弹窗问题真因与 8080 静态同步（本轮）：用户仍看到弹窗内容异常，实测定位为 **8080（Django）服务的是 STATIC_ROOT 旧构建**——源码/新 dist 已含修复，但 collectstatic 未同步，8080 的 HTML 仍引用旧 CSS（hash 不匹配），弹窗仍在旧样式下被裁切、负责人仍是 UUID。修复：`uv run python main.py collect_static` 重新同步 + 重启 Django（`main.py dev web` 启动时会重跑 collectstatic）。复验：8080 引用 `admin-CJ4WreXk.css`（含 `calc(85vh - 48px)` 弹窗规则），playwright 实测 8080 与 3000 双端口 1280x720/1366x768 下编辑/关闭弹窗 footer 可见、body 可滚动、负责人显示「冒烟管理员」、无 JS 错误。**运维要点：前端改动后需 `vite build` + `collect_static` + 重启 Django，8080 才生效；3000 开发端 HMR 即时生效。**
- HR 弹窗/表单布局两个根因修复（本轮，用户持续反馈后定位）：① 职位描述「测试看板」竖排——全局 element-plus.scss 的 `.el-form-item__label{ display:block; width:100% !important }` 覆盖 EP 内联 label-width（88px），把默认（label-right）布局表单内容区挤成 0 宽，textarea 只剩 22px 竖排；共 16 个 HR 表单受影响，内核 85 个全是 label-top 不受影响。修复：全宽规则收窄为 `.el-form--label-top .el-form-item__label`，默认布局恢复 EP 内联宽度。② SPA 深子路由直接刷新白屏——vite.config.ts base 被 65c5ff8 改成 `'./'`，/admin/hr/jobs 直接加载时资源解析成 /admin/hr/assets/ 404。修复：`base: mode === 'production' ? ENV.VITE_BASE_PATH : './'`（生产绝对 /admin/、开发保持相对）。另发现 STATIC_ROOT 实为 apps/static，且 pg/redis/minio 容器会因宿主机事件整批退出需重启。playwright 实测：8080 F5 子路由正常、编辑弹窗 9 label 88px、textarea 484px 横排；3000 登录页恢复；vue-tsc/eslint/vite build 通过。
- 面试功能不可用根因修复（本轮）：职位展开行「候选人」页签永远显示 0 人 → 无面试/AI/Offer 按钮 → 面试无法使用。根因：后端 get_job 把完整申请记录放在 result["applications"]，前端读取的是 jobDetails[].assignments（字段名不匹配），所有职位展开行都空。修复：get_job 同步返回 assignments（与 candidates 详情一致），新增回归测试 1 例（assignments 含 application_id/current_stage/agent）。playwright 端到端：展开行显示候选人、面试弹窗正常打开、安排面试保存成功、全局面试页出现记录；HR 全量 448 tests OK、ruff 通过。
- HR 前端全量实测审计（本轮）：用 playwright 把 16 个页面 + 全部核心流程实测一遍，发现并修复第二个同类 bug——面试官指派失败：创建面试选成员保存报「User is not a workspace member」。根因：services/application_service.py 的 _interviewer_user_id 还在用内核 get_user_members（精简部署返回空），而 serializers/recruitment.py 的同名方法已修过（此前遗漏 service 侧）。修复：改 hr_members 回退，新增回归测试 1 例（内核成员空时创建面试不误报）。全量审计结论：Pipeline 阶段流转/回退原因、简历库/库内候选人、候选人详情/匹配页签、Agent 工作台/运行详情、语义检索（python 返回空是数据事实非 bug，数据分析返回 5 条）、人事成员/审计日志、新建职位/库/候选人、编辑保存、简历上传、我的面试/反馈提交全部正常；共修 2 个字段/成员解析类 bug，HR 全量 449 tests OK。
- AI 功能全链路验证与打通（本轮，全部交给我决定）：实测确认 LLM（sensenova-6.8-flash-lite）在 default 工作区本就配置，AI 链路真实可用——JD 起草 SUCCEEDED（真实调用 482+407 tokens、生成完整 JD、前端草稿抽屉正常打开、含采纳/忽略按钮）；Screening 此前 SKIP 根因是 default 工作区 agent_enable_screening=False（配置项），已开启并确认后续按阶段门控正常（非 APPLIED 阶段才跳过）；Sourcing 失败为「无沉睡候选人」领域原因非 bug。测试时发现 AI 运行是异步串行的（并发上限 2），多次点击会排队，属正常行为。测试产生的 9 条 JD 运行/9 条提案已清理。
- 职位匹配不到简历正文候选人的根因修复（本轮）：用户导入 4 份简历建营销岗，匹配返回 0。根因有三：① 匹配只对 candidate.skills 做精确相等匹配，而 4 份导入简历解析出的 skills 全为空（解析器未提取），且其他候选人的 skills 是长句（如「2.根据市场营销计划」）无法精确命中「营销」；② 即使简历正文（paragraph）含营销内容也不参与匹配。修复 match_job_candidates：新增 子串命中（skills 长句）、简历正文关键词召回（paragraph ILike，按需求技能预聚合 candidate_id）、dense 语义检索（跳过脏技能预筛）三路合并，同分按导入时间排序（新导入优先）。实测营销岗匹配 0→87 人，皮茗婵/潘承/卜君 排进前三、姚舒（无营销）正确排除；新增回归测试 1 例（技能空但正文含技能时召回），HR 全量 450 tests OK。
- 简历解析器技能提取改为 LLM 增强（本轮，用户问怎么设计）：确认 docx 文本提取与语义切片（LLM）本就正常，短板是字段抽取的 parse_resume_text 纯正则、技能只认「个人技能/特长」小节，无专门技能栏的简历技能全空。方案：基础字段保留正则，技能提取走 LLM（复用管道已有 _llm_chat_fn），失败回退规则结果。新增 extract_skills_llm（resume_parser.py，prompt 输出 JSON 数组 + 清洗去重校验），parse_resume_task 接入。实测新上传简历解析出 9 个干净营销技能；并回填用户导入的 4 位候选人技能（卜君 14 个含新媒体运营/微博微信营销/内容营销、皮茗婵含市场营销等）。新增单元测试 4 例，HR 全量 454 tests OK。注意：celery worker 需重启加载新代码（旧 worker 仍消费导致第一次验证失败，已清掉全部旧 worker 重启单个）。
- 技能提取与切片合并为一次 LLM 调用（本轮，用户指出跑两遍 LLM 浪费）：split_resume_with_skills 一次调用同时产出语义切片与技能（扩展切片 prompt 增加 skills 输出 + _parse_skills 解析清洗），parse_resume_task 改为先合并调用再建候选人，预切片传给 index_resume（其本就支持 chunks 参数）不再二次调模型；_index_resume 支持 chunks/split_stats 透传。实测 flow 日志 llm_calls=1（原 2），技能与切片同一上下文产出；split_resume_text 保持向后兼容委托。新增单测 2 例，HR 全量 456 tests OK。
- 简历解析/检索架构落地（本轮，按用户设计）：① parse_resume_text 瘦身——只抽 姓名/电话/邮箱，城市/学历/年限/技能不再规则解析（正则不可靠，技能字段恒空由检索按需处理）；② LLM 只负责切片（撤回 prompt 的 skills 输出，任务不再用技能）；③ 段落生成按句读边界拆 <=100 字子段（_split_pieces），稀疏关键词密度更高；④ ResumeFile 加 raw_text（迁移 0029）+ pg_trgm GIN 索引，解析任务存储 docx 原文；⑤ search_resumes 包一层 wrapper：关键字腿（原文/段落 OR ILIKE 保证召回）在 impl 返回后统一合并，覆盖所有模式与早期返回路径，尊重硬条件槽位过滤，meta 加 keyword_recall。实测：新简历技能空/raw_text 存/段落<=100 字；搜 Flink 语义外追加 keyword 命中。新增单测 3 例，HR 全量 457 tests OK。
- 全量回归测试（本轮，用户要求"进行测试"）：后端全量 511 tests OK（hr/application/knowledge/models_provider/ops/common）、ruff 干净、makemigrations --check/migrate --check 无未应用迁移、vue-tsc 通过、HR 目标文件 ESLint 0 error、vite build 通过、collectstatic 重新同步。清理 3 个旧 celery worker（14:44/21:23/21:37 启动、持旧代码、直接挂 /init 无 supervisor，已 kill -9，仅留 22:21 新 worker）。
- 前端技能字段适配（本轮，用户选择）：候选人列表「按技能搜索」在技能恒空后对新简历失效——后端 _filter_candidates 的 skills 筛选改为「结构化技能字段 OR 简历原文/正文」三路（raw_text ILIKE 优先 + 段落 content ILIKE 兜底存量，多词 AND 语义，distinct 去重）；前端筛选 placeholder 改为「技能 / 简历关键词（逗号分隔，全部命中）」。新增回归测试 1 例（无技能字段候选人按正文关键词命中 / 结构化字段不受影响 / 多词混用 AND），HR 全量 512 tests OK。实测线上：skills=Java→3、营销→86（皮茗婵/潘承/卜君 排前）、销售→180、Python→4、数据库→42；vue-tsc/eslint/vite build/collectstatic 通过，8080 已服务新构建。
- 检索质量端到端实测与 keyword 腿噪声修复（本轮，用户选择 ①）：用 8 组真实职位需求实测三路融合，暴露核心质量问题——**keyword 腿 OR 语义 + 高频词把无关简历灌进结果**：「Python 后端开发」分词出 [Python, 开发]，开发命中 198/266（74%）→ OR 腿把 72 个不含 Python 的简历全部追加；销售/客户/内容/产品/需求/分析/服务/市场/活动 等常见词命中面 60-86%，keyword 腿形同噪声。修复 _keyword_recall_docs：① 高频无区分度词剔除（命中面 > max(30, 50% 语料) 的 term 不进 keyword 腿，交给语义腿；meta.keyword_recall 新增 dropped_terms 透出）；② 段落查询限定 resume 文档集（不再扫同知识库非简历文档）；③ keyword 命中按「命中词数」降序排序（多词命中优先，替代原 DB 顺序）；返回改为 (hits, dropped_terms) 元组。实测修复后：「Python 后端开发」→ dropped 开发、added=0、纯语义 10 条；纯「销售」→ dropped 销售、added=0、10 条语义排序；「Java 后端」→ dropped 服务/开发、added=2、ls_1243（Java+Spring+微服务+MySQL）置顶；营销/销售岗/产品经理等保留低频腿（渠道/商务/拓展/原型/用户…）仍保证召回并按词数排序。新增回归测试 2 例（高频词剔除后 keyword 腿不追加无关简历 / 原 raw_text+段落命中用例适配元组返回），HR 全量 513 tests OK、ruff 干净。语料事实：266 份简历语义索引 100% 覆盖（无 document_id 缺口）；英文技术词（Python/Spark/Vue 等）在语料中命中≈0 属数据事实，非 bug。
- 前端技能字段适配（本轮，用户选择）：候选人列表「按技能搜索」在技能恒空后对新简历失效——后端 _filter_candidates 的 skills 筛选改为「结构化技能字段 OR 简历原文/正文」三路（raw_text ILIKE 优先 + 段落 content ILIKE 兜底存量，多词 AND 语义，distinct 去重）；前端筛选 placeholder 改为「技能 / 简历关键词（逗号分隔，全部命中）」。新增回归测试 1 例（无技能字段候选人按正文关键词命中 / 结构化字段不受影响 / 多词混用 AND），HR 全量 512 tests OK。实测线上：skills=Java→3、营销→86（皮茗婵/潘承/卜君 排前）、销售→180、Python→4、数据库→42；vue-tsc/eslint/vite build/collectstatic 通过，8080 已服务新构建。
- 回归测试发现并修复真回归（本轮）：**auto 模式技能词查询被存量 CandidateSkill 数据误杀为 prefilter_empty**——实测「Java」返回空、search_type=prefilter_empty（LLM 解析 skills=['Java'] → phrase 模式 → 预筛 AND candidate_skill EXISTS，而新架构下技能不再提取、存量回填表持旧数据，skill_norm IN ('java') 0 命中 → 提前返回空，语义召回与关键字腿都被挡住，只剩关键字腿粗召回）。修复：结构化预筛移除技能维度——技能词不再是结构化字段，改由关键字腿（原文/段落 ILIKE）+ 稀疏（BM25）+ 密集（语义）在文本里命中；预筛只保留真实硬条件（年限/学历/城市），门控统一为 hard_slots（skills 模式原本就只认 hard_slots）。对应测试 test_prefilter_skills_exists 改写为 test_prefilter_skills_no_longer_gates（存量技能表非空也不再触发预筛）。实测修复后：Java→hybrid_rrf_reranked 5 条语义排序；数据库 42/销售 76/大数据三年经验 78（关键字腿分别追加 37/71/73）；Java Python→skills 模式 skill_ordered_reranked；3年经验 Java→预筛 applied（candidate_count 242，年限≥3 或未知靠后）；全量 511 tests OK。
- 旧框架彻底清理（本轮，用户要求“狠狠清除”）：`Candidate` 13 列（`current_city/target_city/highest_degree/years_experience/skills/source/source_type/source_detail/collected_at/consent_status/consent_version/contact_preference/note`）+ `CandidateSkill` 表已通过 `0030` 物理删列（`maxkb` 库 `22→9` 列，`hr_candidate_skill` 表 `DROP`），`resume_parser/task` 仅 `name/phone/email`，`Candidate` 主链仅三字段（`name` 支持 `phone/email` 模糊），`_semantic_match` 批量 `raw_text` 并校验正文含技能词（`老师 34→3`），`knowledge/folders` 根自愈，前端 `candidates` 三件套精简至 `422行`（表/弹窗/详情仅三字段），`search` 移除旧展示；`DB` 列保留兼容期已结束，现 `hard` 态 `474 OK`（纯净收口：`Candidate` 模型 `_LEGACY_FIELDS` 兼容桩、`serializers` 5 死方法、`resume_search`/`ResumeSearchCandidate` 桩字段已移除，`soft` 态不再兼容旧列，已验证 `migrate OK`）。
- 下一步：按评测建议①③升级评测构造/对比更强模型重测，叠加 ≥80 例人工标注集交叉验证后冻结阈值；
  试点观测（采纳率/处理时长）数据支撑后由 ADMIN 显式开启免审分带（保留审计与人工回滚）；
  PRD §7 租户注销门槛现为：本仓库内核与 HR 域阶段 A/B1/B2/B3 已闭环；剩余为 staging 真实注销演练与外部租户平台生命周期接入。若存在独立 Workspace ORM，应将删除事件接入 `system_manage.services.workspace_offboarding.offboard_workspace`。

## 5. 测试环境注意

- settings 中 `TEST.TEMPLATE=DB_NAME`：首次创建测试库会用开发库做模板（开发库含演示数据时，按整表计数的旧单测会失败）。
- 正确姿势：`--keepdb` 复用干净测试库；若测试库被污染，重建空库并装 vector 扩展：
  ```sql
  DROP DATABASE IF EXISTS test_maxkb;
  CREATE DATABASE test_maxkb;
  \\c test_maxkb; CREATE EXTENSION IF NOT EXISTS vector;
  ```
- Offer 发送守卫：未审批（APPROVED）不能 SENT；同 Application/指派至多一条 SENT（R3 验收）。
