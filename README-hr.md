# MaxKB 人事招聘工作台（ATS）

## 1. 项目定位

MaxKB v2 精简内核 + 多租户人事招聘工作台：

```text
Workspace
   ├─ ResumeDatabase（总库 + 业务库）
   │    └─ ResumeDatabaseMembership → ResumeFile → Candidate
   └─ Candidate（人才库，仅 姓名/电话/邮箱，简历原文通过 RAG 检索）
        └─ Application（候选人在某职位的流程）
             ├─ JobStage（可配置招聘 Pipeline）
             ├─ Application.status（ACTIVE / HIRED / REJECTED / WITHDRAWN / CLOSED）
             └─ ApplicationEvent / Activity（不可变账本）
```

RAG 已交付；Agent 采用 `Propose → Confirm → Execute`，只给证据和提议，由人确认后走 ATS 命令。

## 2. 当前状态

| 模块 | 状态 |
|---|---|
| 企业知识库 / RAG 内核 | 已交付 |
| 简历语义检索 | 已交付：pgvector+tsvector → RRF(k=60) → bge-reranker-v2-m3 → Small-to-Big；recall@5=0.92；支持多库范围 |
| 简历多库 | 已交付：总库 + 多业务库、多对多成员关系、重复文件复用、归档和库内上下文 |
| 当前 ATS 主链 | `Application + JobStage + ApplicationEvent`；旧固定状态机仅作为迁移基线 |
| ATS 目标设计 | `Application + JobStage + StageHistory`，见 `docs/ATS-STATE-MACHINE-V2.md` |
| Agent | D1 Screening、D2 JD/Interview Copilot、D3 Sourcing/沟通草稿及 D4 Agent 工作台首版已实现；Screening 默认关闭，按 workspace 灰度启用；后续补跨页指标、原文定位和反馈重试表单 |

## 3. 权威文档

| 文档 | 用途 |
|---|---|
| `docs/PRD.md` | 产品基线 |
| `docs/ATS-STATE-MACHINE-V2.md` | 新 ATS 目标设计 |
| `docs/ATS-OPENSOURCE-REFERENCE.md` | 传统 ATS 开源调研（Harly / OpenCATS） |
| `docs/ATS-DESIGN-SPEC.md` | 当前代码事实，只用于迁移对照 |
| `docs/PRD-AGENT-RAG.md` | Agent + RAG 设计 |
| `docs/RAG-V2-DESIGN.md` | 已交付简历 RAG 设计 |
| `docs/RESUME-DATABASES.md` | 总库、多业务库和库内页面设计 |
| `docs/HR-FRONTEND-GUIDE.md` | 人事部前端使用流程指导（操作手册） |
| `docs/DEPLOYMENT.md` | 生产部署清单 |

## 4. 开发与测试

环境变量：

```bash
export MAXKB_CONFIG_TYPE=ENV \
  MAXKB_DB_NAME=maxkb MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
  MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
  MAXKB_DB_ENGINE=django.db.backends.postgresql MAXKB_DB_MAX_OVERFLOW=10 \
  MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_PASSWORD= \
  MAXKB_REDIS_DB=0 MAXKB_REDIS_MAX_CONNECTIONS=10
```

```bash
# 后端
uv run python apps/manage.py test hr.tests application.tests knowledge.tests models_provider.tests ops.tests common.tests --keepdb
uv run python apps/manage.py makemigrations --check --dry-run
uv run python apps/manage.py migrate --check
uv run ruff check apps/hr

# 前端
cd ui
pnpm exec vue-tsc --build
pnpm exec vite build
```

## 5. License

GPL-3.0，继承自 MaxKB。
