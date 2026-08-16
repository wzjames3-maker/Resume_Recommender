# MaxKB 人事招聘工作台（ATS）

## 1. 项目定位

MaxKB v2 精简内核 + 多租户人事招聘工作台：

```text
Candidate（人才库）
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
| 简历语义检索 | 已交付：pgvector+tsvector → RRF(k=60) → bge-reranker-v2-m3 → Small-to-Big；recall@5=0.92 |
| 当前 ATS 代码 | 旧固定状态机，仅作为迁移基线 |
| 目标 ATS | `Application + JobStage + StageHistory`，见 `docs/ATS-STATE-MACHINE-V2.md` |
| Agent | 设计完成，未实现 |

## 3. 权威文档

| 文档 | 用途 |
|---|---|
| `docs/PRD.md` | 产品基线 |
| `docs/ATS-STATE-MACHINE-V2.md` | 新 ATS 目标设计 |
| `docs/ATS-OPENSOURCE-REFERENCE.md` | 传统 ATS 开源调研（Harly / OpenCATS） |
| `docs/ATS-DESIGN-SPEC.md` | 当前代码事实，只用于迁移对照 |
| `docs/PRD-AGENT-RAG.md` | Agent + RAG 设计 |
| `docs/RAG-V2-DESIGN.md` | 已交付简历 RAG 设计 |
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
