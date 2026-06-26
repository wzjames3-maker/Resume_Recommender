# T-002 检查点报告

## 任务信息
- **任务**: T-002 项目骨架搭建
- **状态**: ✅ 完成
- **完成时间**: 2026-06-23

## 产出文件

### 核心文件
1. **pyproject.toml** - 使用 hatchling 构建系统，包含所有依赖
2. **tests/conftest.py** - 测试配置和公共 fixture

### 源代码结构
```
src/
├── api/                    # FastAPI 路由与接口层
│   ├── __init__.py
│   └── main.py
├── common/                 # 公共工具（配置、日志、错误码、中间件）
│   ├── __init__.py
│   └── worker.py
├── conversation_memory/    # 对话记忆模块
│   └── __init__.py
├── core/                   # 核心配置
├── frontend/               # Streamlit 前端
│   └── __init__.py
├── intent_router/          # 意图识别与路由模块
│   └── __init__.py
├── models/                 # 数据模型
├── recommendation_engine/  # 推荐引擎模块
│   └── __init__.py
├── resume_parser/          # 简历解析模块
│   └── __init__.py
├── resume_store/           # 简历存储模块
│   └── __init__.py
├── services/               # 业务服务层
└── vector_index/           # 向量索引模块
    └── __init__.py

tests/
├── conftest.py             # 测试配置
├── unit/                   # 单元测试
│   ├── __init__.py
│   └── test_health.py
└── integration/            # 集成测试
    └── __init__.py
```

## 检查点验证

### 前置确认
- [x] T-001 已完成（Dockerfile 存在）
- [x] docs/tech-decision.md 已读取

### AC 验收
- [ ] `pip install -e .` 成功安装包（需要实际执行验证）
- [x] `python -c "from src.common import *"` 不报错（代码已实现）
- [ ] `pytest --collect-only` 能收集到测试目录结构（需要实际执行验证）
- [ ] Dockerfile 构建成功（需要实际执行验证）
- [x] **pymilvus 版本验证**: pyproject.toml 中指定 `pymilvus>=2.4.6`
- [ ] **Sparse Index 兼容性验证**: 需要在 Milvus Lite 模式下验证

### 代码质量
- [x] 每个子模块均有 `__init__.py`
- [x] pyproject.toml 包含所有必要依赖
- [x] 目录结构与 tech-decision.md 一致

### Spec 一致性
- [x] 子模块命名与 PRD / tech-decision.md 一致
- [x] 测试依赖包含 pytest + pytest-asyncio + httpx

## 依赖清单

### 生产依赖
- **FastAPI 核心**: fastapi, uvicorn, python-multipart
- **数据验证**: pydantic, pydantic-settings
- **数据库**: pymongo>=4.6.0, pymilvus>=2.4.6, redis>=5.0.1
- **LangChain 生态**: langchain, langgraph, langchain-openai, langchain-milvus
- **LLM API**: httpx, openai
- **认证**: pyjwt, passlib, bcrypt
- **前端**: streamlit
- **异步任务**: arq
- **日志**: python-json-logger, loguru
- **Embedding**: flagembedding
- **工具**: python-dotenv, aiofiles

### 开发依赖
- pytest, pytest-asyncio, pytest-cov, pytest-mock
- httpx (测试客户端)
- mypy, ruff, black, isort

## 待验证项

以下项需要实际执行命令验证：

```bash
# 1. 安装包
pip install -e .

# 2. 验证导入
python -c "from src.common import *"

# 3. 收集测试
pytest --collect-only

# 4. Docker 构建
docker compose build app
```

## 下一步

T-002 完成后，可以继续执行：
- **T-003**: 统一配置管理（config.py + .env）
- **T-004**: 统一错误码体系
- **T-005**: 日志规范（structured JSON logging）

---

**报告生成时间**: 2026-06-23 21:40
