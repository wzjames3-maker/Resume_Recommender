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

1. R1：`JobStage` / `Application` / `ApplicationEvent` 迁移与模型；
2. R2：命令服务与 API（`move_stage` / `reject` / `withdraw` / `close` / `restore`）；
3. R3：Interview / Offer / Handoff 改挂 Application；
4. R4：前端动态 Pipeline；
5. R5：测试与迁移回归；
6. D1：Screening Agent。
