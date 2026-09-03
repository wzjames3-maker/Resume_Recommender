# 简历推荐 · 多租户人事招聘工作台（ATS）

> 基于**精简版 MaxKB v2 RAG 内核**构建的轻量招聘工作台：企业知识库 + 简历语义检索 + 招聘流程管理 +“提议-确认-执行”的 AI 助手。

![License](https://img.shields.io/badge/License-GPL--3.0-blue) ![Python](https://img.shields.io/badge/Python-3.11-green) ![Django](https://img.shields.io/badge/Django-5.2-green) ![Vue](https://img.shields.io/badge/Vue-3.4-green) ![DB](https://img.shields.io/badge/PostgreSQL%2Bpgvector-blue)

---

## 1. 产品定位

面向已在使用 MaxKB 工作区的中小招聘团队，在保留企业知识库 RAG 底座的同时，内嵌多租户招聘模块——管理**候选人、招聘需求、候选人在具体职位中的招聘流程**，以及与招聘有关的简历和面试资料。

产品方向：

```text
MaxKB RAG 内核 + 传统 ATS 流程 + “提议-确认-执行”的 Agent（AI 只建议，人做决策）
```

本产品是**轻量 ATS（Applicant Tracking System）**，不是独立的 HRIS/HCM：不建设组织树、员工档案、薪酬、合同、考勤或入职手续；Offer 被接受后，系统记录招聘结果并向既有 HRIS / OA 或人工交接流程输出所需信息。

**隐私与合规原则**：候选人及简历数据是独立业务数据，默认不进入知识库、Embedding 索引或模型上下文；只收集完成招聘所需的最小字段，联系方式按角色默认脱敏，全程审计可追溯。

## 2. 核心特性

| 模块 | 能力 |
|---|---|
| **企业知识库（RAG 内核）** | 文档解析与切片、`pgvector + tsvector` 双路召回、RRF 融合、rerank、Small-to-Big 精排、对话 API（SSE / OpenAI 兼容协议） |
| **简历语义检索** | `pgvector + tsvector → RRF(k=60) → bge-reranker-v2-m3 → Small-to-Big`；`recall@5 = 0.92`；支持跨库范围检索，简历原文通过 RAG 检索，人才画像无需人工录入 |
| **简历库体系** | 总库 + 多业务库、多对多成员关系、同库资源复用、按 `workspace + SHA-256` 去重、库归档与库内上下文 |
| **招聘流程（ATS）** | `Candidate`（候选人）`/ Job`（招聘需求）`/ Application`（职位申请流程）`/ Interview`（面试）`/ ResumeFile`（简历文件）完整业务对象；`JobStage` 可配置招聘 Pipeline；状态机守卫（`PENDING_SCREEN → SCREEN_PASSED → INTERVIEWING → OFFER → HIRED` 及受控终止），越权迁移一律拒绝 |
| **不可变账本与审计** | `ApplicationEvent` 记录每次操作、`HrAuditLog` 全量审计（对象、动作、结果、IP）；误拒绝可由管理员恢复并记录原因 |
| **AI 助手（Agent）** | D1 简历初筛（默认关闭，按 workspace 灰度）、D2 JD/面试 Copilot、D3 寻源与沟通草稿、D4 Agent 工作台；统一 `HrAgentRun → HrAgentProposal`，`Propose → Confirm → Execute`，AI 不自动淘汰候选人、不发放 Offer |
| **权限与多租户** | 招聘查看者 / 操作员 / 管理员三级访问资格；所有资源持久化 `workspace_id`，服务端从认证主体派生租户，跨租户资源按不存在处理 |

### 核心业务对象速览

代码与设计文档中大量使用英文对象名，与中文业务的对应关系如下：

| 对象（代码/文档） | 中文 | 一句话说明 |
|---|---|---|
| `Candidate` | 候选人 | 人才库里的人：仅登记姓名、手机号、邮箱与状态（`ACTIVE` 有效 / `ARCHIVED` 归档）；简历原文通过 RAG 检索，不手工录技能画像 |
| `Job` | 招聘需求（职位） | 一项正在招人的需求：部门、城市、职级、计划人数、技能要求、负责人与状态（草稿 / 招聘中 / 暂停 / 关闭） |
| `Application` | 职位申请流程 | **候选人 × 职位**的关联记录：渠道（投递 / 主动寻访 / 内推 / 猎头推荐）、当前进度（`PENDING_SCREEN` 待筛选 → `SCREEN_PASSED` 筛选通过 → `INTERVIEWING` 面试中 → `OFFER` → `HIRED` 录用 / `REJECTED` 拒绝）、当前负责人；是招聘流程的核心载体 |
| `Interview` | 面试 | 候选人在某职位的面试轮次、面试官、时间与反馈 |
| `ResumeFile` | 简历文件 | 上传的简历原件（docx / txt）：按内容哈希去重、异步解析提取文本、进入语义索引供检索；同一切片不重复入库 |
| `JobStage` | 招聘阶段 | 可配置的招聘 Pipeline 阶段序列 |
| `ApplicationEvent` | 流程事件 | 每次状态或操作变更的不可变记录（审计账本），可解释、可追溯 |
| `HrAgentRun` / `HrAgentProposal` | AI 助手运行 / 提议 | AI 助手的执行记录与提交给人工的"提议"，遵循 `Propose → Confirm → Execute`（提议 → 确认 → 执行），AI 不自动决策 |

> 历史说明：早期文档中的 `CandidateAssignment` 即现在的 `Application`（职位申请流程），二者指同一业务对象。

## 3. 架构概览

```text
┌─ 前端 ─────────────────────────────────────────────────┐
│  Vue 3 + Element Plus（admin SPA / chat embed SPA）     │
└───────────────────────┬────────────────────────────────┘
                        │ /admin/api、/chat/api（DRF · Swagger: /admin/api-doc）
┌───────────────────────▼────────────────────────────────┐
│  Django 5.2 · Python 3.11                               │
│   ├─ apps/hr            招聘工作台 ATS（领域模型/服务/视图/Agent）│
│   ├─ apps/knowledge     RAG 知识库（解析 / 切片 / 向量检索）        │
│   ├─ apps/application · apps/chat   应用配置与对话 API            │
│   └─ apps/models_provider   模型提供方抽象（LLM / Embedding）      │
└───────┬──────────────────────────────┬──────────────────┘
        │                              │
┌───────▼───────────┐        ┌─────────▼─────────┐
│ PostgreSQL（pgvector）│        │ Redis（缓存/队列）  │
│ · Django ORM        │        │ · Celery 异步任务   │
└────────────────────┘        └───────────────────┘
```

**技术栈**：Python 3.11 · Django 5.2 · DRF · Celery（`uv` 管理依赖）；Vue 3 · Vite · Element Plus · md-editor-v3；PostgreSQL + pgvector · Redis 7；模型调用统一走 OpenAI 兼容协议（自定义 API Key 即可接入）。

## 4. 仓库布局

| 路径 | 说明 |
|---|---|
| `apps/hr/` | 招聘工作台：模型（`recruitment.py`）、服务层、视图、Agent（`agents/`）、异步任务（`task/`） |
| `apps/knowledge/` | RAG 知识库：文档解析、段落切片、Embedding 与向量检索 |
| `apps/application/`、`apps/chat/` | 应用配置与对话 API（SSE 流式协议） |
| `apps/models_provider/` | 模型提供方抽象，注册 LLM / Embedding 类型 |
| `ui/` | 前端 SPAs（`npm run dev` 管理端 / `npm run chat` 对话端） |
| `docs/` | 产品与设计文档（见 §6） |
| `main.py` | 生产/开发入口（`python main.py dev` 等） |

## 5. 快速开始

依赖：Python 3.11（`uv`）、PostgreSQL 15+（含 `pgvector` 扩展）、Redis 7、Node.js 18+。

```bash
# 1. 环境变量（.env：MAXKB_CONFIG_TYPE=ENV）
export MAXKB_CONFIG_TYPE=ENV \
  MAXKB_DB_NAME=maxkb MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
  MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=你的密码 \
  MAXKB_DB_ENGINE=django.db.backends.postgresql \
  MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_PASSWORD=

# 2. 后端（自动 collectstatic + migrate，监听 0.0.0.0:8080）
python main.py dev
# 标准入口：python manage.py runserver 0.0.0.0:8080

# 3. 前端（Vite dev server 代理 /admin/api、/chat/api → :8080）
cd ui && npm install && npm run dev

# 4. 测试与静态检查
uv run python manage.py test hr.tests application.tests knowledge.tests \
  models_provider.tests ops.tests common.tests --keepdb
uv run ruff check apps/hr
cd ui && npm run type-check
```

生产部署见 `docs/DEPLOYMENT.md`；人事部操作手册见 `docs/HR-FRONTEND-GUIDE.md`。

## 6. 权威文档

| 文档 | 用途 |
|---|---|
| `docs/PRD.md` | 产品基线（业务对象、规则、上线门槛） |
| `docs/ATS-STATE-MACHINE-V2.md` | 目标 ATS 状态机设计 |
| `docs/ATS-OPENSOURCE-REFERENCE.md` | 传统开源 ATS 调研（Harly / OpenCATS） |
| `docs/ATS-DESIGN-SPEC.md` | 当前代码事实，仅迁移对照 |
| `docs/PRD-AGENT-RAG.md` | Agent + RAG 智能化设计 |
| `docs/RAG-V2-DESIGN.md` | 已交付的简历 RAG 设计 |
| `docs/RESUME-DATABASES.md` | 总库、多业务库与库内页面设计 |
| `docs/DEPLOYMENT.md` | 生产部署清单 |
| `docs/HR-FRONTEND-GUIDE.md` | 人事部前端使用流程（操作手册） |

## 7. 交付状态

| 模块 | 状态 |
|---|---|
| 企业知识库 / RAG 内核 | ✅ 已交付 |
| 简历语义检索（recall@5=0.92） | ✅ 已交付 |
| 简历多库 / 去重 / 归档 | ✅ 已交付 |
| ATS 主链（`Application + JobStage + ApplicationEvent`） | ✅ 已交付（目标设计见 §6） |
| AI 助手 D1–D4 | ✅ 已实现（Screening 默认关闭，按 workspace 灰度启用） |
| 权限 / 审计 / PII 最小化 | ✅ 已交付 |

## 8. License

**GPL-3.0**，继承自 MaxKB；本 fork 及其后续代码必须保持 GPL-3.0 开源。

> 派生声明与裁剪范围记录见仓库内 `docs/` 归档与提交历史。