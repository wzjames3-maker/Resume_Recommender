# 智能招聘 RAG 推荐系统

基于 RAG（检索增强生成）的企业智能招聘助手，通过自然语言交互帮助 HR 高效筛选和推荐候选人。

## ✨ 功能特性

- 🔍 **智能候选人检索**：支持自然语言描述招聘需求
- 💬 **多轮对话交互**：支持条件修正、追问等多轮对话
- 📄 **多格式简历解析**：支持 PDF、DOCX、JSON、图片（OCR）
- 🎯 **精准推荐**：Hybrid Retrieval（Dense + Sparse）+ Rerank
- 📊 **可解释推荐**：每个推荐附带评分、理由、技能匹配分析
- 🔒 **数据安全**：PII 字段加密存储，RBAC 权限控制

## 🏗️ 技术架构

- **后端**：Python + FastAPI
- **Agent 编排**：LangGraph
- **向量数据库**：Milvus
- **文档数据库**：MongoDB
- **缓存**：Redis
- **LLM**：DeepSeek / OpenAI
- **Embedding**：BGE-M3
- **前端**：Streamlit

## 📦 项目结构

```
├── src/
│   ├── api/                      # FastAPI 接口层
│   │   └── v1/                   # API v1 版本
│   ├── common/                   # 公共模块
│   │   ├── auth.py               # JWT 认证
│   │   ├── config.py             # 统一配置
│   │   ├── errors.py             # 错误码体系
│   │   └── logger.py             # 日志模块
│   ├── resume_parser/            # 简历解析模块
│   │   ├── text_extractor.py     # 文本提取
│   │   ├── ocr_extractor.py      # OCR 提取
│   │   ├── llm_extractor.py      # LLM 结构化提取
│   │   ├── segmenter.py          # 语义段落切分
│   │   └── skill_normalizer.py   # Skill 标准化
│   ├── resume_store/             # 简历存储模块
│   │   ├── repository.py         # 数据仓库层
│   │   └── desensitizer.py       # 数据脱敏
│   ├── vector_index/             # 向量索引模块
│   │   ├── embedding_generator.py # Embedding 生成
│   │   └── vector_writer.py      # 向量写入
│   ├── intent_router/            # 意图路由模块
│   │   ├── classifier.py         # 意图分类器
│   │   └── router.py             # 路由分发器
│   ├── recommendation_engine/    # 推荐引擎模块
│   │   ├── hybrid_retriever.py   # 混合检索
│   │   ├── metadata_filter.py    # 元数据过滤
│   │   └── reranker.py           # Rerank 重排序
│   ├── conversation_memory/      # 对话记忆模块
│   │   ├── session_manager.py    # 会话管理
│   │   └── workflow.py           # 端到端工作流
│   └── frontend/                 # Streamlit 前端
│       ├── app.py                # 主应用
│       └── components.py         # UI 组件
├── tests/                        # 测试代码
├── data/                         # 数据文件
├── docs/                         # 文档
├── specs/                        # 规格说明
├── tasks/                        # 任务文件
├── docker-compose.yml            # Docker 编排
├── Dockerfile                    # Docker 构建
├── pyproject.toml                # Python 项目配置
└── .env.example                  # 环境变量示例
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repo-url>
cd 简历推荐系统

# 复制环境变量
cp .env.example .env

# 编辑 .env 文件，填入 API Key 等配置
vim .env
```

### 2. Docker 启动

```bash
# 启动所有服务
docker compose up -d

# 查看服务状态
docker compose ps
```

### 3. 访问服务

- **API 文档**：http://localhost:8000/docs
- **Streamlit 前端**：http://localhost:8501
- **Milvus 控制台**：http://localhost:9091

### 4. 测试账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin123 | 管理员 |
| hr | hr123 | HR |
| viewer | viewer123 | 只读 |

## 📖 API 使用

### 登录

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "hr", "password": "hr123"}'
```

### 搜索候选人

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我找3年Java经验在北京的候选人"}'
```

### 上传简历

```bash
curl -X POST http://localhost:8000/api/v1/resumes/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@resume.pdf"
```

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行单元测试
pytest tests/unit/

# 运行集成测试
pytest tests/integration/

# 运行特定模块测试
pytest tests/resume_parser/
pytest tests/intent_router/
pytest tests/recommendation_engine/
```

## 📚 文档

- [PRD 文档](docs/PRD.md) - 产品需求文档
- [技术选型](docs/tech-decision.md) - 技术选型决策
- [API 规格](specs/) - API 接口规格
- [部署文档](docs/deployment.md) - 部署指南

## 🔧 开发

### 本地开发

```bash
# 安装依赖
pip install -e ".[dev]"

# 启动 FastAPI
uvicorn src.api.main:app --reload

# 启动 Streamlit
streamlit run src/frontend/app.py
```

### 代码规范

```bash
# 代码格式化
black src/ tests/
isort src/ tests/

# 代码检查
ruff check src/ tests/

# 类型检查
mypy src/
```

## 📊 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit 前端                           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI API 层                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ /chat    │  │ /upload  │  │ /login   │  │ /conv    │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Intent Router                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ classify │  │ extract  │  │   route  │  │ fallback │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Recommendation Engine                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ retrieve │  │  filter  │  │  rerank  │  │  reason  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Milvus    │  │   MongoDB    │  │    Redis     │
│  向量索引    │  │  文档存储     │  │   缓存       │
└──────────────┘  └──────────────┘  └──────────────┘
```

## 📈 性能指标

- 搜索响应时间：< 500ms (P95)
- 推荐准确率：Top-10 采纳率 ≥ 80%
- 首轮筛选时间：减少 70%

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License
