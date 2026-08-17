# 项目交接（当前状态）

## 0. 一句话

MaxKB v2 精简内核 + `apps/hr` 人事招聘工作台。RAG 已交付；ATS 需要从旧固定状态机重构为传统 ATS 的 `Application + JobStage + StageHistory`；Agent 设计已完成，在 ATS v2 之后实施。

## 1. 必须读的文档

| 文档 | 内容 |
|---|---|
| `docs/PRD.md` | 产品基线 |
| `docs/ATS-STATE-MACHINE-V2.md` | 新 ATS 目标设计（当前最重要的重构依据） |
| `docs/ATS-OPENSOURCE-REFERENCE.md` | 传统 ATS 开源调研 |
| `docs/ATS-DESIGN-SPEC.md` | 当前代码事实，仅迁移对照 |
| `docs/PRD-AGENT-RAG.md` | Agent + RAG 设计 |
| `docs/RAG-V2-DESIGN.md` | 已交付简历 RAG 设计 |
| `docs/DEPLOYMENT.md` | 部署清单 |

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
3. RAG 链路保持已交付形态，只允许给 `search_resumes` 增加可选 `candidate_id/document_ids` 限定召回范围。
4. Agent 只有 Proposal 一个写出口；人工确认后调用 ATS 命令。
5. 测试 Key 不是安全问题，但正式环境必须使用环境变量注入正式 Key。

## 4. 下一步

- R1（基础模型与命令服务）、R2（Job 两阶段关闭 STRICT/BULK）、R3（Interview/Offer/Handoff 挂 Application + Offer 接受联动 HIRED）、R4（前端动态 Pipeline 看板）、R5（API 权限/幂等/终态矩阵测试）已完成，HR 全量 419 tests 通过。
- 新增：`POST/GET /hr/jobs/{job_id}/close(-preview)`、`/hr/applications/{id}/interviews|offers`；`search_resumes` 增加可选 `candidate_id/document_ids` 范围限定；存量 CandidateAssignment 迁移已内建为迁移 0025 的 RunPython 数据兜底（幂等锚点 ApplicationEvent(IMPORTED)），原 `import_legacy_assignments` 管理命令随重构移除。
- D1 Screening Agent 已完成：`hr_agent_run` / `hr_agent_proposal` 模型与 0022 迁移、
  `apps/hr/agents/` 包（Runner 固定顺序工具编排 + PII 上下文投影 + 服务端评分派生建议动作 + Proposal 审批）、
  Application 创建时 APPLY/REFERRAL 自动触发（celery-once 防重）、并发/速率护栏、LLM 失败降级 run=FAILED 业务零影响；
  API：`POST /hr/agents/SCREENING/run`、`POST /hr/proposals/{id}/accept|dismiss`、`GET /hr/applications/{id}/proposals`；
  审计新增 AGENT_RUN/AGENT_DECIDE（HrAuditLog 已补 trace_id）。
- D2 已完成：企业知识库工具 search_knowledge（HrConfig.agent_knowledge_bases 白名单 + PII 掩码）、similar_jobs（SQL 相似 + HIRED 画像）、JD 起草 Agent（JD_DRAFT，propose DRAFT target=JOB，采纳仅写字段需 ADMIN）与 Interview Copilot（INTERVIEW_COPILOT，prepare 面试题 / feedback 评估草稿，仅本人面试官或 OPERATOR+ 触发）、AgentRunAPI 支持三 Agent、job/interview proposals 列表、AI 设置页知识库白名单、职位 JD 草稿抽屉与我的面试 AI 助手；迁移 0023，HR 全量 486 tests 通过。
- D3 已完成：Sourcing 人才库激活（SOURCING，沉睡候选人池 + 硬条件核对 + 激活清单 DRAFT×JOB）、
  沟通草稿助手（COMMUNICATION_DRAFT，REJECT/PROGRESS/FAQ/OTHER 话术 + 企业话术库）、
  反馈闭环统计（GET /hr/agents/stats，agent_type × 动作 × 分数带采纳率，工作台采纳率卡片）、
  真实模型探针管理命令 `hr_agent_probe`（RUN_REAL_MODEL=1 + 环境变量凭据，验证 JSON 能力与 Screening 端到端）；
  迁移 0024，HR 全量 500 tests 通过。
- D1 评测标定基线已完成（2026-08-17，真实模型）：`import_resume_dataset`（数据集/train.json 300 份语料导入，
  预切片免 LLM 切片 + 幂等 + 同步向量化）、`eval_screening`（正/负画像配对 + 4 并发真实 Screening，
  报告 docs/screening-eval-2026-08-17.json 与 docs/SCREENING-EVAL-2026-08-17.md）；
  基线 200 例宽松一致率 72%（正 44% / 负 100%），未达 ≥80% 目标——诊断：泛技能职位构造 +
  flash-lite 保守评估（正样本误拒）、LLM 校验失败 13%；建议评测构造升级（完整 JD）与模型档位对比后再标定。
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
- 部署验证（PRD §8，2026-08-17）已完成：Celery worker+beat 真实调度（探针文件、任务注册、beat 19:00 派发→worker 执行）、
  对象存储私有读（匿名 403/签名 200）、备份加密+恢复演练+轮转（Salted__/pg_restore 624 条目）、日志 PII 脱敏复核（无真实泄露）、
  .env.example 600/默认 DEBUG=False、PG 连接加密补齐（MAXKB_DB_SSLMODE→OPTIONS sslmode）；报告 docs/DEPLOYMENT-VERIFY-2026-08-17.md。
  租户注销/数据返还阶段 A、B1、B2 已实现（见下条新增记录）；若未来接入外部租户平台，仅需让其 Workspace 删除事件调用本仓库的统一 callback。
- 租户注销/数据返还（设计稿阶段 A，2026-08-18）已完成并提交：新增 hr_offboard tombstone（0026 迁移，幂等锚点+留痕：执行人/时间/各表计数/导出包路径，注销后唯一保留的 HR 记录）、
  hr_offboard_workspace <workspace_id> [--dry-run|--force|--export <dir>|--user-id <uuid>] 命令（默认即审计+清理；dry-run 只统计；export 先出脱敏 JSON 数据返还包再清理；force 绕过活跃守卫：有 PENDING/RUNNING Agent 运行 / ACTIVE 申请 / 非 CLOSED 职位时拒绝）、
  清理顺序严格按「先子后父、先账本后配置」：简历语义索引 delete_resume_knowledge 批量删文档/段落/向量/知识库（含孤儿）→ 流程对象与级联子对象 → 职位/阶段 → 候选人 → 简历文件 → 配置/授权/审计/流转日志 → 存储对象缺失容忍；
  全程审计 EXPORT/DELETE 行随 hr_audit_log 一并清空，存证以 hr_offboard 为准；
  hr.tests 新增 HrOffboardCommandTests 7 例（全量归零/索引与存储清空/dry-run 与实际计数一致/幂等重入报已注销/跨工作区隔离/守卫拒绝/导出脱敏+路径留痕），HR 全量 440 tests OK + ruff 干净；
  已在真实开发库端到端验证：offboard-e2e 工作区 23 行/1 存储文件清零、7 段导出 JSON 脱敏（138****5678 / e2***@example.com）、二次执行报已注销不重删。
- 租户注销阶段 B1（2026-08-18）已完成：新增 `hr.services.offboarding` callback contract（preview/export/offboard），命令与 callback 共用无输出执行器；新增 HR ADMIN 范围内的 preview/export/purge Web API，POST 强制 `confirm_workspace_id`，可返回脱敏数据返还包；新增权限、跨工作区、导出不落库、确认、防误删与活跃守卫测试。当前精简内核没有统一 Workspace ORM/注销生命周期，因此 B2 仍需由实际内核生命周期调用该 callback，并补齐内核其它域与统一对象存储编排。
- 租户注销阶段 B2（2026-08-18）已完成：新增 `WorkspaceOffboard` 统一跨域 tombstone、`WorkspaceOffboardingService` 与 `workspace_offboard` 命令；编排 application/knowledge/model/权限/映射/日志/chat/HR，按资源 ID 精确清理内核文件，外层事务提交后统一回收 HR 对象存储；新增 Workspace ADMIN 系统 API 与 HR「租户注销」页面，支持预览、脱敏返还包、确认、force、事务失败回滚和幂等；system_manage 4 例、全量后端 501 tests OK，vue-tsc/admin build OK。
- 下一步：按评测建议①③升级评测构造/对比更强模型重测，叠加 ≥80 例人工标注集交叉验证后冻结阈值；
  试点观测（采纳率/处理时长）数据支撑后由 ADMIN 显式开启免审分带（保留审计与人工回滚）；
  PRD §7 租户注销门槛现为：本仓库内核与 HR 域阶段 A/B1/B2 已闭环；外部租户平台若存在独立 Workspace ORM，应将删除事件接入 `system_manage.services.workspace_offboarding.offboard_workspace`。

## 5. 测试环境注意

- settings 中 `TEST.TEMPLATE=DB_NAME`：首次创建测试库会用开发库做模板（开发库含演示数据时，按整表计数的旧单测会失败）。
- 正确姿势：`--keepdb` 复用干净测试库；若测试库被污染，重建空库并装 vector 扩展：
  ```sql
  DROP DATABASE IF EXISTS test_maxkb;
  CREATE DATABASE test_maxkb;
  \\c test_maxkb; CREATE EXTENSION IF NOT EXISTS vector;
  ```
- Offer 发送守卫：未审批（APPROVED）不能 SENT；同 Application/指派至多一条 SENT（R3 验收）。
