# 简历推荐 RAG 系统 — 修复方案 Review（已修正）

## Context

基于修复后 Review 发现的 10 个 Task，逐项审查具体实现方案的正确性和可行性。
审查结论：7 项方案正确可直接执行，3 项需修正后执行。
审批通过后将本修正版文档保存到项目 `tasks/` 目录。

---

## 一、方案审查结果总览

| Task | 问题 | 结论 | 备注 |
|------|------|------|------|
| Task 1 | N-01 SessionManager 异步/同步重构 | ⚠️ 需补充 | 遗漏 `_list_redis` 改造 |
| Task 2 | N-02 /health 连接泄漏 | ⚠️ 需调整 | `app.state` + 改签名过度设计 |
| Task 3 | N-03 LOG_LEVEL 配置字段 | ✅ 正确 | 直接执行 |
| Task 4 | N-04 count_sessions 方法 | ⚠️ 需补充 | `_count_user_sessions` 实现缺失 |
| Task 5 | N-05 Worker Redis 密码 | ✅ 正确 | 直接执行 |
| Task 6 | Q-05 Milvus 表达式注入 | ✅ 正确 | 直接执行 |
| Task 7 | Q-01 JWT 错误泄露 | ✅ 正确 | 直接执行 |
| Task 8 | Q-02 登录日志脱敏 | ✅ 正确 | 直接执行 |
| Task 9 | Q-03 access_logs 有界 | ✅ 正确 | 可考虑更优方案 |
| Task 10 | Q-04 桩函数标记 | ✅ 正确 | 直接执行 |

---

## 二、需修正的 3 项方案

### Task 1 修正: 遗漏 `_list_redis` 改造

**文件**: `src/conversation_memory/session_manager.py`

**现状**: L295-304 的 `_list_redis()` 是 `async def`，内部调用 `redis._get_redis()` 获取原始 async client 执行 `await r.smembers()` 和 `await redis._load()`。
**问题**: 方案只提到改公共方法和 `_RedisSessionBackend`，遗漏了这个私有辅助方法。
**修正**: `_list_redis` (L295-304) 改为同步方法 `_list_redis_sync`:

```python
def _list_redis_sync(self, redis_backend: _RedisSessionBackend, user_id: str) -> List[SessionState]:
    r = redis_backend._get_redis()  # 现在返回同步 redis.Redis
    members = r.smembers(f"{_RedisSessionBackend._USER_INDEX_PREFIX}{user_id}")
    sessions = []
    for sid in members:
        s = redis_backend._load(sid)  # 现在是同步方法
        if s and s.status == SessionStatus.ACTIVE:
            sessions.append(s)
    sessions.sort(key=lambda s: s.last_active_at, reverse=True)
    return sessions
```

`list_sessions` (L270-293) 中移除 asyncio 桥接，直接调用 `_list_redis_sync`。

### Task 2 修正: 避免过度设计

**文件**: `src/api/main.py`

**现状方案**: 在 `lifespan()` 创建连接存到 `app.state`，health_check 加 `request: Request` 参数。
**问题**:
1. `health_check` 是 `async def`，但方案用同步 `redis.from_url()` — 虽然可行但不一致
2. MongoDB 已通过 `mongodb_connection` 单例复用，Redis/Milvus 应同模式
3. 改签名增加不必要复杂度

**修正方案**: 创建模块级健康检查连接，lifespan 管理生命周期:

```python
# main.py 模块级
_health_redis: Optional[redis.Redis] = None
_health_milvus: Optional[MilvusClient] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 现有 MongoDB 连接 ...
    global _health_redis, _health_milvus
    _health_redis = redis.from_url(settings.redis.redis_url, socket_connect_timeout=2)
    _health_milvus = MilvusClient(uri=settings.milvus.MILVUS_URI, timeout=3)
    yield
    # ... 现有清理 ...
    if _health_redis: _health_redis.close()
    if _health_milvus: _health_milvus.close()

@app.get("/health")
async def health_check():
    # 直接用模块级变量，不改签名
    try:
        _health_redis.ping()
        status["redis"] = "ok"
    except Exception:
        status["redis"] = "unavailable"
    try:
        status["milvus"] = "ok" if _health_milvus.get_server_version() else "unavailable"
    except Exception:
        status["milvus"] = "unavailable"
```

### Task 4 修正: 补充 `_count_user_sessions` 实现

**文件**: `src/conversation_memory/session_manager.py`

**现状方案**: `count_sessions` 调用 `redis._count_user_sessions()`，但该方法在 `_RedisSessionBackend` 中不存在。
**修正**: 在 Task 1 重构后的 `_RedisSessionBackend` 中新增:

```python
def _count_user_sessions(self, user_id: str) -> int:
    """统计用户的会话数量（同步）"""
    redis = self._get_redis()
    return redis.scard(f"{self._USER_INDEX_PREFIX}{user_id}")
```

Task 4 依赖 Task 1 先完成（因为 `_RedisSessionBackend` 需要先改为同步）。

---

## 三、可直接执行的 7 项方案

### Task 3: LOG_LEVEL
**文件**: `src/common/config.py` L37 后
```python
LOG_LEVEL: str = Field(default="INFO", description="日志级别")
```

### Task 5: Worker Redis
**文件**: `src/common/worker.py`
删除 `import os`，`redis_settings` 从 `get_settings().redis` 构建:
```python
from src.common.config import get_settings
_settings = get_settings()

class WorkerSettings:
    redis_settings = RedisSettings(
        host=_settings.redis.REDIS_HOST,
        port=_settings.redis.REDIS_PORT,
        database=_settings.redis.REDIS_DB,
        password=_settings.redis.REDIS_PASSWORD,
    )
```

### Task 6: Milvus 注入防护
**文件**: `src/conversation_memory/workflow.py` L258
```python
import re
_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')

# L258 后插入:
safe_ids = [cid for cid in candidate_ids if _SAFE_ID_RE.match(cid)]
if len(safe_ids) < len(candidate_ids):
    logger.warning(f"过滤了 {len(candidate_ids) - len(safe_ids)} 个非法 candidate_id")
candidate_ids = safe_ids
```

### Task 7: JWT 错误
**文件**: `src/common/auth.py` L100-105
```python
except jwt.InvalidTokenError:
    raise AuthenticationError(
        error_code=ErrorCode.AUTH_004,
        detail="Token 无效",
    )
```

### Task 8: 登录日志
**文件**: `src/api/v1/auth.py` L48
```python
logger.info("收到登录请求")
```

### Task 9: access_logs 有界
**文件**: `src/resume_parser/pii_handler.py`
添加 `_MAX_ACCESS_LOGS = 1000`，L290 `append` 后截断:
```python
self._access_logs.append(log)
if len(self._access_logs) > self._MAX_ACCESS_LOGS:
    self._access_logs = self._access_logs[-self._MAX_ACCESS_LOGS:]
```
> 更优方案: 既然 L296-301 已写 MongoDB，可考虑移除内存列表，`get_access_logs` 改为从 MongoDB 查询。

### Task 10: 桩函数
**文件**: `src/common/worker.py` L22-26
```python
async def process_resume(ctx, resume_id: str):
    logger.warning("process_resume 是桩函数，尚未实现真实逻辑")
    print(f"Processing resume: {resume_id}")
    return {"status": "stub", "resume_id": resume_id}
```

---

## 四、实施顺序（修正后）

| 轮次 | Task | 涉及文件 | 预估时间 |
|------|------|---------|----------|
| 第一轮 | Task 1 + Task 4 (N-01 + N-04) | `session_manager.py` | 1 天 |
| 第二轮 | Task 2 + Task 3 (N-02 + N-03) | `main.py`, `config.py` | 2 小时 |
| 第三轮 | Task 5 + Task 6 (N-05 + Q-05) | `worker.py`, `workflow.py` | 1 小时 |
| 第四轮 | Task 7-10 (Q-01~Q-04) | `auth.py`, `pii_handler.py`, `worker.py` | 45 分钟 |

> Task 1 和 Task 4 合并到第一轮，因为 Task 4 的 `_count_user_sessions` 依赖 Task 1 的同步重构。

## 五、验证方式

1. `pytest tests/` 全部通过
2. `python -c "from src.common.config import get_settings; s = get_settings(); print(s.app.LOG_LEVEL)"` → `INFO`
3. `curl /health` → 返回各组件状态，不产生新连接（验证方式：连续调用两次，第二次不应有新连接日志）
4. 生产环境启动后，SessionManager 通过 Redis 正常存取会话，`list_sessions` 正常返回
5. Worker `redis_settings` 正确读取环境变量密码
6. `conversations` API 的 `total` 字段返回正确数量
