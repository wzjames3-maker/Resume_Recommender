# T-002: 项目骨架搭建

## 基本信息
- 对应 Spec: tech-decision.md 决策项1（FastAPI）、决策项2（Streamlit）
- 对应 AC: 无（基础设施）
- 依赖: T-001
- 预计工时: 0.5 天

## 输入
- docs/tech-decision.md
- Dockerfile（来自 T-001）

## 输出
- src/ 包结构（含 `__init__.py`）
- pyproject.toml
- tests/ 目录结构

## 实现要求
1. 创建 Python 包结构 `src/`，包含以下子模块：
   - `resume_parser/` — 简历解析模块
   - `intent_router/` — 意图识别与路由模块
   - `recommendation_engine/` — 推荐引擎模块
   - `conversation_memory/` — 对话记忆模块
   - `resume_store/` — 简历存储模块
   - `vector_index/` — 向量索引模块
   - `api/` — FastAPI 路由与接口层
   - `frontend/` — Streamlit 前端
   - `common/` — 公共工具（配置、日志、错误码、中间件等）
2. 每个子模块包含 `__init__.py`
3. 创建 `pyproject.toml`，使用 hatchling/setuptools 构建系统，包含所有依赖：
   - fastapi, uvicorn, streamlit
   - pydantic, pydantic-settings
   - pymongo >= 4.6
   - pymilvus >= 2.4.6  # ⚠️ 版本锁死：必须 >=2.4.6 才完整支持 SPARSE_FLOAT_VECTOR + SPARSE_INVERTED_INDEX。低于此版本在 Milvus Lite 下 Sparse Index 创建会静默失败。
   # Lite/Standal一致性保障：pymilvus 版本必须与 docker-compose 中 milvusdb/milvus 镜像版本对齐（建议 pymilvus 2.4.x + milvus 2.4.x）
   - python-json-logger
   - PyJWT
   - openai / langchain（按 tech-decision.md 决策项）
   - pytest, pytest-asyncio, httpx（测试依赖）
4. 创建 `tests/` 目录，结构与 `src/` 对齐：
   - `tests/unit/` — 各模块单元测试
   - `tests/integration/` — 集成测试
   - `tests/conftest.py` — 公共 fixture
5. 确保 Dockerfile 中的 COPY 和入口点与包结构一致

## 验收检查点

### 前置确认
- [ ] T-001 已完成（Dockerfile 存在）
- [ ] docs/tech-decision.md 已读取

### AC 验收
- [ ] `pip install -e .` 成功安装包
- [ ] `python -c "from src.common import *"` 不报错
- [ ] `pytest --collect-only` 能收集到测试目录结构
- [ ] Dockerfile 构建成功
- [ ] **pymilvus 版本验证**: `pip show pymilvus` 版本 >= 2.4.6，且与 Milvus Standalone 镜像版本大版本对齐（均为 2.4.x）
- [ ] **Sparse Index 兼容性验证**: 在 Milvus Lite 模式下执行 `create_indexes()` 创建 SPARSE_INVERTED_INDEX 不报错

### 代码质量
- [ ] 每个子模块均有 `__init__.py`
- [ ] pyproject.toml 包含所有必要依赖
- [ ] 目录结构与 tech-decision.md 一致

### Spec 一致性
- [ ] 子模块命名与 PRD / tech-decision.md 一致
- [ ] 测试依赖包含 pytest + pytest-asyncio + httpx

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry < 3 → 修复 | retry = 3 → BLOCKED
