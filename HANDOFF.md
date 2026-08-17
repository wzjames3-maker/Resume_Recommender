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
- 新增：`POST/GET /hr/jobs/{job_id}/close(-preview)`、`/hr/applications/{id}/interviews|offers`；`search_resumes` 增加可选 `candidate_id/document_ids` 范围限定；`import_legacy_assignments` 管理命令（幂等迁移存量 CandidateAssignment）。
- D1 Screening Agent 已完成：`hr_agent_run` / `hr_agent_proposal` 模型与 0022 迁移、
  `apps/hr/agents/` 包（Runner 固定顺序工具编排 + PII 上下文投影 + 服务端评分派生建议动作 + Proposal 审批）、
  Application 创建时 APPLY/REFERRAL 自动触发（celery-once 防重）、并发/速率护栏、LLM 失败降级 run=FAILED 业务零影响；
  API：`POST /hr/agents/SCREENING/run`、`POST /hr/proposals/{id}/accept|dismiss`、`GET /hr/applications/{id}/proposals`；
  审计新增 AGENT_RUN/AGENT_DECIDE（HrAuditLog 已补 trace_id）。
- D2 已完成：企业知识库工具 search_knowledge（HrConfig.agent_knowledge_bases 白名单 + PII 掩码）、similar_jobs（SQL 相似 + HIRED 画像）、JD 起草 Agent（JD_DRAFT，propose DRAFT target=JOB，采纳仅写字段需 ADMIN）与 Interview Copilot（INTERVIEW_COPILOT，prepare 面试题 / feedback 评估草稿，仅本人面试官或 OPERATOR+ 触发）、AgentRunAPI 支持三 Agent、job/interview proposals 列表、AI 设置页知识库白名单、职位 JD 草稿抽屉与我的面试 AI 助手；迁移 0023，HR 全量 486 tests 通过。
- 下一步：D3 Sourcing 人才库激活 + 沟通草稿 + 免审分带配置（采纳率报表进 dashboard）。

## 5. 测试环境注意

- settings 中 `TEST.TEMPLATE=DB_NAME`：首次创建测试库会用开发库做模板（开发库含演示数据时，按整表计数的旧单测会失败）。
- 正确姿势：`--keepdb` 复用干净测试库；若测试库被污染，重建空库并装 vector 扩展：
  ```sql
  DROP DATABASE IF EXISTS test_maxkb;
  CREATE DATABASE test_maxkb;
  \\c test_maxkb; CREATE EXTENSION IF NOT EXISTS vector;
  ```
- Offer 发送守卫：未审批（APPROVED）不能 SENT；同 Application/指派至多一条 SENT（R3 验收）。
