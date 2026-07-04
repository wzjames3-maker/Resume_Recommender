# 简历推荐 RAG 系统 — 生产环境代码审查报告

## Context

项目为企业级智能招聘 RAG 推荐系统（FastAPI + Milvus + MongoDB + Redis + Streamlit），在代码审查中发现多项生产环境严重问题，涵盖安全漏洞、架构缺陷、代码 Bug 和运维隐患。

---

## 一、P0 — 安全问题（必须立即修复）

### S-01 API 密钥明文提交至代码库
- `.env` 包含 4 个真实 `sk-*` 密钥、PII Fernet 密钥、JWT 弱密钥、MongoDB/MinIO 明文密码
- **修复**：立即轮换所有密钥；用 BFG 清理 Git 历史；更新 `.env.example` 为占位符
- **文件**：`.env`, `.env.example`, `.gitignore`

### S-02 硬编码默认用户及弱密码
- `user_store.py` 硬编码 admin/admin123、hr/hr123、viewer/viewer123，MongoDB 失败时静默回退
- **修复**：生产环境禁止回退到默认用户，MongoDB 失败应抛异常
- **文件**：`src/common/user_store.py`, `src/common/config.py`

### S-03 JWT 密钥可预测
- `JWT_SECRET_KEY=resume-rag-jwt-secret-key-2026` 可被猜测
- **修复**：生产用 `secrets.token_hex(64)` 生成随机密钥
- **文件**：`.env.example`, `src/common/config.py`

### S-04 Redis URL 缺少密码
- `docker-compose.yml` 中 `REDIS_URL=redis://redis:6379/0` 无密码，但 Redis 启动带 `--requirepass`
- **修复**：改为 `redis://:${REDIS_PASSWORD:-password}@redis:6379/0`
- **文件**：`docker-compose.yml`

### S-05 审计日志用户提取未实现
- `audit_log.py` 中 `_extract_user_id()` 含 TODO，始终返回 None
- **修复**：实现 JWT 解码提取 `sub` 字段
- **文件**：`src/common/middleware/audit_log.py`

### S-06 MongoDB/MinIO 使用默认弱密码
- MongoDB `password`、MinIO `minioadmin/minioadmin` 硬编码
- **修复**：改为环境变量注入，不设默认值
- **文件**：`.env.example`, `docker-compose.yml`

---

## 二、P1 — 架构与 Bug（高优先级）

### Bug 类

#### B-01 workflow.search() enriched 结果被丢弃（死代码）
- `workflow.py` L126-165 构建 `enriched` 列表，但 L168 传递原始 `retrieval_results` 给 metadata_filter
- **修复**：L168 改为 `self.metadata_filter.filter(enriched, merged_slots)`
- **文件**：`src/conversation_memory/workflow.py`

#### B-02 N+1 查询问题
- workflow 循环中逐条调用 `self.resume_repository.get(r.resume_id)`，top_k=50 产生 50 次 MongoDB 查询
- **修复**：收集所有 resume_id 后用 `$in` 批量查询
- **文件**：`src/conversation_memory/workflow.py`, `src/resume_store/repository.py`

#### B-03 上传索引失败静默忽略
- `upload.py` 向量索引写入失败只记日志不报错，简历"上传成功"但搜不到
- **修复**：增加 `index_status` 字段，失败时提示用户
- **文件**：`src/api/v1/upload.py`

### 架构类

#### A-01 会话管理器仅内存存储
- `SessionManager._sessions` 为内存 dict，重启丢失，不支持多 Worker
- **修复**：实现 Redis 会话后端，利用已有 Redis 基础设施
- **文件**：`src/conversation_memory/session_manager.py`

#### A-02 限流器仅内存存储
- `RateLimiter` 注释写着"生产应使用 Redis"但用的是内存 defaultdict
- **修复**：Redis 滑动窗口限流
- **文件**：`src/common/rate_limiter.py`

#### A-03 异步上下文中同步阻塞调用
- `chat.py` async 函数内调用 `httpx.Client`（同步）阻塞事件循环
- **修复**：短期用 `asyncio.to_thread()` 包装，中期改 `httpx.AsyncClient`
- **文件**：`src/api/v1/chat.py`, `src/intent_router/classifier.py`, `src/vector_index/embedding_generator.py`, `src/recommendation_engine/reranker.py`

#### A-04 httpx.Client 每次新建连接
- embedding/classifier/reranker 每次 API 调用新建 httpx.Client，无连接复用
- **修复**：类级别共享 Client 实例 + 连接池
- **文件**：同上

#### A-05 Embedding 缓存无上限
- `EmbeddingGenerator._cache` 无界 dict，无 TTL，内存持续增长
- **修复**：使用 `cachetools.TTLCache` 或 `functools.lru_cache`
- **文件**：`src/vector_index/embedding_generator.py`

#### A-06 PII 访问日志仅内存存储
- `PIIHandler._access_logs` 内存列表，重启丢失合规审计记录
- **修复**：写入 MongoDB 集合或结构化日志
- **文件**：`src/resume_parser/pii_handler.py`

#### A-07 全局单例模式问题
- 模块级全局实例（`hybrid_retriever`, `reranker` 等）import 时创建，非线程安全
- **修复**：改用 FastAPI 依赖注入 + lifespan 管理
- **文件**：多个模块

---

## 三、P2 — 运维与健壮性（中优先级）

#### O-01 健康检查为浅层检查
- `/health` 只返回静态 JSON，不检查下游服务
- **修复**：增加 MongoDB/Milvus/Redis 连通性检查
- **文件**：`src/api/main.py`

#### O-02 Dockerfile 单容器双进程
- `CMD` 用 `&` 跑 streamlit + uvicorn，无进程管理
- **修复**：拆分为两个独立容器
- **文件**：`Dockerfile`, `docker-compose.yml`

#### O-03 /test-error 端点暴露
- 生产环境暴露异常测试端点
- **修复**：条件注册，仅 dev 环境可用
- **文件**：`src/api/main.py`

#### O-04 CORS_ORIGINS 解析错误
- `.env` 中 `CORS_ORIGINS=["http://localhost:8501"]` 含 JSON 方括号，解析后 origin 不匹配
- **修复**：`.env` 去掉方括号，或解析兼容 JSON 数组
- **文件**：`.env`, `src/api/main.py`

#### O-05 validation handler 始终返回详情
- 验证错误在生产环境也返回完整 detail
- **修复**：增加 debug 模式判断
- **文件**：`src/common/errors.py`

#### O-06 MongoDB 连接无重连机制
- 单例连接断开后不会自动重连
- **修复**：增加 ping 检查 + 自动重连
- **文件**：`src/resume_store/connection.py`

#### O-07 无优雅关闭机制
- 无 lifespan/shutdown 处理，关闭时不清理资源
- **修复**：FastAPI lifespan 管理连接生命周期
- **文件**：`src/api/main.py`

---

## 四、实施顺序

| 轮次 | 内容 | 预估时间 |
|------|------|---------|
| **第一轮** | S-01 → S-03 → S-04 → S-06 → S-02 → S-05 | 1 天 |
| **第二轮** | B-01 → B-02 → B-03 → A-03 → A-04 → A-01 | 3-5 天 |
| **第三轮** | A-02 → A-05 → A-06 → A-07 → O-04 → O-03 | 1-2 周 |
| **第四轮** | O-01 → O-02 → O-05 → O-06 → O-07 | 1 周 |

## 五、验证方式

1. **安全修复验证**：检查 `.env` 不在 Git 中，新密钥可正常调用 API，Redis 连接正常
2. **Bug 修复验证**：上传简历后搜索可找到（B-01/B-03），搜索响应时间下降（B-02）
3. **架构验证**：重启后对话历史保留（A-01），多 Worker 限流生效（A-02），并发请求不阻塞（A-03）
4. **运维验证**：`curl /health` 返回组件状态（O-01），容器独立运行（O-02）
5. **回归测试**：`pytest tests/` 全部通过