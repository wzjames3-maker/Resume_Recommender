# 简历推荐 · 多租户人事招聘工作台（ATS）

> 简历智能检索 + 招聘流程管理 + AI 助手（提议-确认-执行），基于精简版 MaxKB RAG 内核构建。

---

## 项目简介

给中小招聘团队使用的轻量招聘系统（ATS，Applicant Tracking System），内置在企业知识库（RAG）之上。

使用方式很简单：**上传简历 → 语义检索找人 → 挂到职位上走招聘流程 → AI 助手辅助筛选和沟通**。

两点原则贯穿始终：

- **AI 只建议，人做决策**——AI 不自动淘汰候选人、不发 Offer、不改招聘状态。
- **候选人数据与知识库隔离**——只收集招聘必需信息，联系方式默认脱敏，全程留审计记录。

## 核心功能

- **简历语义检索**：按意思找简历，而非只按关键词。`pgvector + tsvector` 双路召回 → RRF 融合 → 重排（rerank），实测 `recall@5 = 0.92`。
- **简历库管理**：总库 + 多业务库；同一份简历只存一份（SHA-256 去重）；支持归档与库内检索。
- **招聘流程管理**：职位、候选人、申请、面试全流程；招聘阶段（Pipeline）可配置；状态迁移有守卫，非法操作一律拒绝。
- **全程审计可追溯**：每一步操作都记入不可变账本；误拒绝可由管理员恢复并留痕。
- **AI 助手（D1–D4）**：简历初筛、JD/面试 Copilot、寻源与沟通草稿、Agent 工作台；初筛默认关闭，按工作区灰度开启。
- **权限与合规**：查看者 / 操作员 / 管理员三级权限；多租户数据隔离；PII（个人敏感信息）最小化。

## 核心对象

| 英文名 | 中文 | 说明 |
|---|---|---|
| `Candidate` | 候选人 | 人才库里的人，只登记姓名、手机号、邮箱和状态 |
| `Job` | 招聘需求 | 一项正在招人的职位，如"后端工程师 ×3" |
| `Application` | 申请流程 | 候选人和职位的绑定：渠道、进度、负责人——招聘流程的核心 |
| `Interview` | 面试 | 某候选人在某职位的面试轮次、面试官和反馈 |
| `ResumeFile` | 简历文件 | 上传的简历原件，去重、解析后进入检索索引 |
| `ApplicationEvent` | 流程事件 | 每次状态变更的不可变记录（审计账本） |

## 技术栈

- 后端：Python 3.11 · Django 5.2 · DRF · Celery（依赖用 uv 管理）
- 前端：Vue 3 · Element Plus · Vite
- 存储：PostgreSQL（pgvector 向量检索）· Redis
- 模型：OpenAI 兼容接口，自备 API Key 即可接入

## 快速开始

依赖：Python 3.11（uv）、PostgreSQL 15+（pgvector 扩展）、Redis 7、Node.js 18+。

```bash
# 1. 配置环境变量（写入 .env）
export MAXKB_CONFIG_TYPE=ENV \
  MAXKB_DB_NAME=maxkb MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
  MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=你的密码 \
  MAXKB_DB_ENGINE=django.db.backends.postgresql \
  MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_PASSWORD=

# 2. 启动后端（自动建表 + 迁移，监听 8080）
python main.py dev

# 3. 启动前端（另开终端）
cd ui && npm install && npm run dev

# 4. 运行测试
uv run python manage.py test hr.tests application.tests knowledge.tests \
  models_provider.tests ops.tests common.tests --keepdb
```

生产部署见 `docs/DEPLOYMENT.md`；人事部操作手册见 `docs/HR-FRONTEND-GUIDE.md`。

## 项目文档

| 文档 | 内容 |
|---|---|
| `docs/PRD.md` | 产品基线：业务规则、状态机、上线门槛 |
| `docs/ATS-STATE-MACHINE-V2.md` | 目标 ATS 状态机设计 |
| `docs/RAG-V2-DESIGN.md` | 简历 RAG 检索设计 |
| `docs/PRD-AGENT-RAG.md` | AI 助手（Agent）设计 |
| `docs/HR-FRONTEND-GUIDE.md` | 人事部操作手册 |

## License

GPL-3.0，继承自 MaxKB；本项目的后续代码必须保持 GPL-3.0 开源。