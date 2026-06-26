<!-- Spec: security-hardening -->
<!-- Spec Layer: 04 - Business Rules -->
<!-- 迭代类型: Tier M -->
<!-- 代码核对: 2026-06-25 -->

# 安全业务规则

## SEC-RULE-001: RBAC 强制挂载
所有非公开端点（除 /health、/login、/）必须同时满足：
1. `Depends(get_current_user)` 认证
2. `Depends(require_permission("<resource>:<action>"))` 授权

`require_permission` 签名为 `require_permission(*required_permissions: str)`（可变参数，见 rbac.py:150），返回 FastAPI Depends 可用的 `permission_checker`。权限不足抛 `AuthorizationError(AUTH_002, 403)`。

权限标识严格对齐 `rbac.py` 的 `ROLE_PERMISSIONS`，不新增/修改权限矩阵。

## SEC-RULE-002: 资源归属优先于角色
对于带 `{id}` 路径参数的读/写端点：
1. 先查资源存在性 → 不存在返回 `ResourceNotFoundError(CONV_001, 404)`（统一错误码，不用裸 `HTTPException`）
2. 再校验归属：`session.user_id == current_user["sub"]` 或 `current_user["role"] == "admin"`
3. 归属不符返回 404（CONV_001），**不返回 403**，避免资源枚举
4. admin 角色豁免归属校验
5. `repository.get(resume_id, user_id)` 的 `user_id=None` 仅限 admin 内部调用路径；API 层调用必须传当前 user_id

注：`repository.list()` 已强制 `query["user_id"]=user_id`（简历列表已隔离，无需改）。

## SEC-RULE-003: 密钥分离
- JWT 签名密钥：`JWT_SECRET_KEY`（仅用于 JWT 签发/验证）
- PII 加密密钥：`PII_ENCRYPTION_KEY`（Fernet 原生 base64 key，直接传入 `Fernet(key)`，不再 sha256 派生）
- 数据库/缓存密码：各自独立配置项（MONGODB_PASSWORD、REDIS_PASSWORD）
- 禁止任何密钥复用；禁止密钥存在字符串字面量默认值（第三方 LLM/Embedding API Key 除外，允许空串默认）

## SEC-RULE-004: 密钥 fail-fast
- `PII_ENCRYPTION_KEY`、`JWT_SECRET_KEY`、`MONGODB_PASSWORD`、`REDIS_PASSWORD` 的 Field default 改为 `...`（必填）
- `get_settings()` 调用时若缺失，pydantic 抛 `ValidationError`，服务启动失败
- `LLM_API_KEY`/`EMBEDDING_API_KEY`/`OCR_API_KEY`/`RERANKER_API_KEY` 保持空串默认（缺失时业务降级，不阻断启动）

## SEC-RULE-005: 异常信息最小化
- `generic_exception_handler`：debug=False 返回 `detail=None`；debug=True 返回 `str(exc)`（仅开发）
- `AppException.to_response`：debug=False 返回 `detail=None`；debug=True 返回 `self.error_detail`（错误码映射表）
- `app.state.debug` 来源：`settings.app.DEBUG`（AppSettings.DEBUG），生产默认 False
- 日志中仍记录完整 traceback（服务端可见），客户端不可见

## SEC-RULE-006: 文件上传三重校验
1. 扩展名白名单：{.pdf, .docx, .json}（取 `Path(file.filename).suffix.lower()`）
2. MIME 白名单：{application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/json}
3. 大小 ≤ 10MB（`len(content) > 10*1024*1024`）
- 扩展名/MIME 不符 → `ValidationError(RESUME_003, 422)`
- 大小超限 → `ValidationError(RESUME_004, 413)`
- 校验在 MD5 去重检查之前执行
- **必须移除 upload.py 现有 try/except 包裹**（104-123 行），否则异常被吞为 success=False，校验失效

## SEC-RULE-007: CORS 最小化
- `allow_origins` 从 `settings.app.CORS_ORIGINS` 读取（逗号分隔，空时默认 `["http://localhost:8501"]`）
- 禁止 `allow_origins=["*"]` 与 `allow_credentials=True` 同时出现
- `allow_methods` 限定 {GET, POST, DELETE, OPTIONS}
- 生产环境 `CORS_ORIGINS` 必填

## SEC-RULE-008: 登录限流
- 维度：客户端 IP（`request.client.host`，login 端点需新增 `request: Request` 参数）
- 阈值：10 req/min
- 实现：Redis 计数器 + 60s TTL
- 超限：HTTP 429（复用 ErrorCode SYS_004 或新增 RATE_001，本迭代用 SYS_004）
- 限流 key：`ratelimit:login:{ip}`
- 限流在密码校验之前执行（防暴力枚举）
