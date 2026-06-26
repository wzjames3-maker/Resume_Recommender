# SEC-T08: 登录限流

## 基本信息
- **对应 Spec**: SEC-REQ-008, SEC-RULE-008
- **对应 AC**: AC-SEC-008
- **依赖**: SEC-T07
- **预计工时**: 0.5 天
- **优先级**: P1

## 输入
- `src/api/v1/auth.py` login（当前无 Request 参数，无限流）
- Redis 连接（RedisSettings 已有）

## 输出
- `src/common/rate_limiter.py` — 新建，Redis 滑动窗口限流
- 修改 `src/api/v1/auth.py` — login 新增 request: Request + 限流
- `tests/unit/test_rate_limiter.py` — 新增

## 实现要求
1. `rate_limiter.py`：
   ```python
   async def rate_limit(key: str, limit: int, window: int = 60) -> bool:
       """返回 True 允许，False 超限"""
       redis = get_redis()
       current = await redis.incr(key)
       if current == 1:
           await redis.expire(key, window)
       return current <= limit
   ```
2. `auth.py` login 签名新增 `request: Request`：
   ```python
   from fastapi import Request
   from src.common.rate_limiter import rate_limit
   from src.common.errors import AppException, ErrorCode

   @router.post("/login", response_model=LoginResponse)
   async def login(request: LoginRequest, http_request: Request):
       client_ip = http_request.client.host if http_request.client else "unknown"
       allowed = await rate_limit(f"ratelimit:login:{client_ip}", limit=10)
       if not allowed:
           raise AppException(error_code=ErrorCode.SYS_004, detail="请求过于频繁，请稍后重试")
       # ... 原有登录逻辑
   ```
   注意：LoginRequest 与 Request 参数名需区分（http_request）避免冲突
3. 限流在密码校验之前执行
4. 超限返回 429（SYS_004 的 http_status 需确认为 429，若不是则新增 RATE_001 或调整）

## 验收检查点
- [ ] `auth.py` login 含 `http_request: Request` 参数
- [ ] 同 IP 连续 10 次 /auth/login 正常响应
- [ ] 同 IP 第 11 次返回 429
- [ ] 限流在密码校验之前执行
- [ ] 60s 后计数重置可再次登录
- [ ] `tests/unit/test_rate_limiter.py` 通过

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
