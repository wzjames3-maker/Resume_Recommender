# 🎯 简历推荐系统 (Resume Recommender)

企业智能招聘 RAG 推荐系统 —— 基于语义理解的人才库检索与推荐平台。

## 解决的问题

传统 HR 筛选简历依赖关键词搜索 + 人工阅读，面对 10 万+ 历史简历库：

- ❌ "Java 工程师" 搜不到 "Spring Boot 后端开发"
- ❌ 首轮筛选耗时占招聘周期的大头
- ❌ 推荐结果缺乏可解释性
- ❌ 多轮追问（"再推几个"、"学历高一点"）无法被理解

**本系统用语义向量检索 + LLM 多轮对话，让 HR 像跟猎头聊天一样搜简历。**

## 架构

`
┌─────────────────────────────────────────────────┐
│                   Streamlit UI                    │
│           (聊天式交互 / 简历上传 / 搜索结果)          │
├─────────────────────────────────────────────────┤
│                   FastAPI 后端                     │
│  ┌──────────┬──────────┬──────────┬──────────┐   │
│  │ 意图路由  │ 简历解析  │ 推荐引擎  │ 对话记忆  │   │
│  │ Intent   │ Resume   │ Recomm.  │ Conv.    │   │
│  │ Router   │ Parser   │ Engine   │ Memory   │   │
│  └──────────┴──────────┴──────────┴──────────┘   │
├─────────────────────────────────────────────────┤
│            向量索引 / 存储 / 任务队列               │
│     Milvus      MongoDB    Redis (ARQ)            │
└─────────────────────────────────────────────────┘
`

## 技术栈

| 层面 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI + Uvicorn | REST API + WebSocket |
| 前端 | Streamlit | 聊天式交互界面 |
| 向量数据库 | Milvus 2.4+ | 混合检索（稠密 + 稀疏向量） |
| 文档数据库 | MongoDB | 简历存储 + PII 加密 |
| 缓存/队列 | Redis + ARQ | 会话缓存 + 异步任务 |
| LLM 编排 | LangChain + LangGraph | RAG 流程 + Agent 工作流 |
| Embedding | OpenAI / 兼容 API | 文本向量化 |
| 容器化 | Docker Compose | 一键部署 |

## 核心模块

| 模块 | 路径 | 功能 |
|------|------|------|
| 简历解析 | src/resume_parser/ | PDF/DOCX 解析 → 分段 → LLM 提取 → PII 脱敏 |
| 意图路由 | src/intent_router/ | 用户意图分类 + 槽位提取 + 回退策略 |
| 推荐引擎 | src/recommendation_engine/ | 混合检索 + 重排序 + 可解释推荐 |
| 对话记忆 | src/conversation_memory/ | 多轮上下文管理 + 指代消解 |
| 向量索引 | src/vector_index/ | Milvus 稠密/稀疏索引管理 |
| 简历存储 | src/resume_store/ | MongoDB CRUD + PII 加解密 |
| API 层 | src/api/ | REST 端点 + 认证中间件 |

## 快速开始

### 环境要求

- Docker & Docker Compose
- Python 3.11+（本地开发）
- OpenAI API Key（或兼容接口）

### 1. 配置环境变量

`ash
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 等配置
`

### 2. 启动服务

`ash
docker compose up -d
`

启动后：
- **Streamlit 前端**: http://localhost:8501
- **FastAPI 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

### 3. 本地开发

`ash
pip install -e ".[dev]"
pytest -v
`

## 项目结构

`
├── src/                     # 源代码
│   ├── api/                 # FastAPI 路由
│   ├── common/              # 公共组件（配置、认证、中间件）
│   ├── conversation_memory/ # 对话记忆模块
│   ├── intent_router/       # 意图路由模块
│   ├── recommendation_engine/ # 推荐引擎
│   ├── resume_parser/       # 简历解析模块
│   ├── resume_store/        # 简历存储模块
│   ├── vector_index/        # 向量索引模块
│   └── frontend/            # Streamlit 前端
├── tests/                   # 测试代码
├── scripts/                 # 工具脚本
├── specs/                   # 模块 Spec 文档
├── docs/                    # 项目文档（PRD / 可行性 / 技术选型）
├── design/                  # UI/UX 设计资产
├── tasks/                   # 任务拆分与进度
├── docker-compose.yml       # 容器编排
└── Dockerfile               # 应用镜像
`

## 开发方式

本项目遵循 **SDD (Spec-Driven Development)** 方法论：
- 人管 Spec，Agent 管代码
- 每个模块有 8 层 Spec 文档（specs/<module>/00~08.md）
- 变更从 Spec 开始，代码是 Spec 的投影

详见 AGENTS.md。

## License

MIT
