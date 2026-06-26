# T-003: 统一配置管理

## 基本信息
- 对应 Spec: tech-decision.md 决策项（配置管理方案）
- 对应 AC: 无（基础设施）
- 依赖: T-002
- 预计工时: 0.5 天

## 输入
- docs/tech-decision.md
- src/common/ 包结构（来自 T-002）
- docker-compose.yml（来自 T-001）

## 输出
- src/common/config.py
- .env.example
- tests/unit/test_config.py

## 实现要求
1. 创建 `src/common/config.py`，使用 `pydantic-settings` 的 `BaseSettings`：
   - `AppSettings`：APP_NAME, APP_ENV (dev/staging/prod), DEBUG, HOST, PORT
   - `LLMSettings`：LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL, LLM_TEMPERATURE, LLM_MAX_TOKENS
   - `EmbeddingSettings`：EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_API_KEY, EMBEDDING_DIMENSION
   - `MilvusSettings`：MILVUS_URI, MILVUS_TOKEN, MILVUS_COLLECTION_PREFIX, MILVUS_DIMENSION
   - MILVUS_VERSION_COMPAT: 记录目标 Milvus 版本（默认 2.4），用于运行时版本对齐检查
   - `RedisSettings`：REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD（用于会话缓存 + ARQ 任务队列 + 分布式缓存）
   - `QueueSettings`：QUEUE_NAME, QUEUE_MAX_JOBS, QUEUE_RETRY（ARQ 异步任务队列配置）

## 验收检查点

### 前置确认
- [ ] T-002 已完成（项目骨架存在）
- [ ] docs/tech-decision.md 已读取

### AC 验收
- [ ] config.py 可正常 import，所有 Settings 类实例化不报错
- [ ] .env.example 包含所有配置项且有合理默认值
- [ ] RedisSettings 连接配置可正确读取
- [ ] QueueSettings 配置可正确读取
- [ ] MILVUS_VERSION_COMPAT 默认值为 2.4

### 代码质量
- [ ] 使用 pydantic-settings 的 BaseSettings
- [ ] 所有配置从环境变量读取，不硬编码
- [ ] 单元测试覆盖各 Settings 类的实例化

### Spec 一致性
- [ ] 配置项与 tech-decision.md 决策项一致
- [ ] Redis 配置与 Tier L 变更一致

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry < 3 → 修复 | retry = 3 → BLOCKED