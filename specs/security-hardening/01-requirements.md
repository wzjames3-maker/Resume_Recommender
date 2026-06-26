<!-- Spec: security-hardening -->
<!-- Spec Layer: 01 - Requirements -->
<!-- 迭代类型: Tier M -->
<!-- 代码核对: 2026-06-25 -->

# 安全加固需求清单

## SEC-REQ-001: RBAC 权限强制启用（P0）
- **来源**: CodeGraph Review #3；PRD §2 权限矩阵（admin 全部 / hr 上传+查询+个人对话 / viewer 只读）；rbac.py 已实现 `require_permission(*perms)` 但 0 端点使用
- **描述**: 所有写操作端点追加 `Depends(require_permission("..."))`，权限标识对齐 `rbac.py` 的 ROLE_PERMISSIONS
- **影响端点与权限**（对齐 PRD UC 与现有 rbac.py 权限集）:
  | 端点 | 权限 | 允许角色（按 ROLE_PERMISSIONS） |
  |------|------|------------------------------|
  | `POST /api/v1/resumes/upload` | `resume:create` | admin, hr |
  | `POST /api/v1/chat` | `conversation:create` | admin, hr（**viewer 无此权限，被拒**） |
  | `GET /api/v1/conversations` | `conversation:read` | admin, hr, viewer |
  | `GET /api/v1/conversations/{id}` | `conversation:read` | admin, hr, viewer |
  | `DELETE /api/v1/conversations/{id}` | `conversation:delete` | admin, hr |
- **说明**: viewer 按 PRD 为"只读：查看推荐结果、候选人详情"，rbac.py 已正确未授予 `conversation:create`/`resume:create`。本需求是**启用**已有实现，不改权限矩阵
- **验收**: viewer token 调用 upload 返回 403 + code=AUTH_002

## SEC-REQ-002: 资源归属校验（IDOR 修复）（P0）
- **来源**: CodeGraph Review #4
- **描述**: 对话 get/delete 必须校验 `session.user_id == current_user.sub`，admin 豁免；归属不符返回 404（防枚举）
- **现状**:
  - `conversations.py` get/delete 取了 user_id 但未校验归属
  - `repository.list()` 已强制 `query["user_id"]=user_id`（简历列表已隔离，无需改）
  - `repository.get()` 的 user_id 可选——简历详情 API 若存在需强制传 user_id（当前无独立简历详情 GET 端点，预留规则）
- **实现**: 校验失败用 `ResourceNotFoundError(CONV_001)` 而非 `HTTPException(404)`，统一错误码体系
- **验收**: 用户 A token GET 用户 B 的 conversation_id 返回 404 + CONV_001

## SEC-REQ-003: 密钥分离与默认值消除（P0）
- **来源**: CodeGraph Review #1 #2
- **现状**:
  - `encryption.py:_get_key` 读 `settings.jwt.JWT_SECRET_KEY` + sha256 派生，`getattr(..., "default-secret-key")` 兜底
  - `config.py` 无 PIISettings；JWT/Mongo/Redis 密钥有字符串默认值
  - Fernet 密钥格式：sha256 派生的 base64（32 字节）——与 Fernet 原生 key 格式兼容
- **描述**:
  - 新增 `PIISettings.PII_ENCRYPTION_KEY: str = Field(...)`（必填），并在 `Settings` 聚合 `pii: PIISettings`
  - `encryption.py._get_key` 改读 `settings.pii.PII_ENCRYPTION_KEY`，直接用作 Fernet key（不再 sha256 派生）
  - 移除 `getattr` 兜底；缺失 PII_ENCRYPTION_KEY 时 `get_settings()` 抛 pydantic ValidationError
  - JWT_SECRET_KEY、MONGODB_PASSWORD、REDIS_PASSWORD 的 default 改为 `...`（必填）
  - LLM_API_KEY / EMBEDDING_API_KEY / OCR_API_KEY 等第三方 key 保持空串默认（本地无 key 时降级，不 fail-fast）
- **密钥迁移**: 现有 phone/email 密文用旧派生 key 加密，换新 key 后无法解密。需迁移脚本：用旧 key 解密 → 用新 PII_ENCRYPTION_KEY 重新加密写回
- **验收**: 不配置 PII_ENCRYPTION_KEY 时服务启动失败；迁移后数据可正常加解密

## SEC-REQ-004: .env 纳入版本控制忽略（P0）
- **来源**: CodeGraph Review #1
- **现状**: 无 `.git`、无 `.gitignore`；`.env` 含真实 `sk-` key；`.env.example` 已用占位符但 env 名与 config 字段不一致
- **描述**:
  - 创建 `.gitignore`（忽略 .env、__pycache__、*.log、.coverage、screenshot_*.png、.codegraph/）
  - 修正 `.env.example`：env 名对齐 config 字段（`DEBUG` 非 `APP_DEBUG`）；新增 `PII_ENCRYPTION_KEY=` 占位
  - 吊销当前泄露的 LLM/OCR/Embedding/Reranker API Key（人工）
- **验收**: `git check-ignore .env` 返回 `.env`；`.env.example` 无 `sk-` 真实值

## SEC-REQ-005: 密码哈希存储（P1）
- **来源**: CodeGraph Review #8
- **现状**: `auth.py:39-55` USERS_DB 硬编码明文；`auth.py:70` 明文比对
- **描述**: 用户表迁移到 MongoDB `users` collection；密码用 bcrypt 哈希（passlib）；移除 USERS_DB
- **验收**: DB 无明文密码；`admin123` 等弱口令不可登录（除非 init 显式设置）

## SEC-REQ-006: CORS 白名单与 debug 配置化（P1）
- **来源**: CodeGraph Review #5 #6
- **现状**:
  - `main.py:21-27` `allow_origins=["*"]` + `allow_credentials=True`
  - `main.py:42` `app.state.debug = True` 硬编码（忽略 config.py 的 `AppSettings.DEBUG`）
  - `errors.py` `generic_exception_handler` debug 时返回 `str(exc)`；`AppException.to_response` debug 时返回 `self.error_detail`
- **描述**:
  - `AppSettings` 新增 `CORS_ORIGINS: str = Field("")`；`main.py` 从 `settings.app.CORS_ORIGINS` 读取（逗号分隔），删除 `["*"]`
  - `main.py` 改 `app.state.debug = settings.app.DEBUG`（不再硬编码 True）
  - 生产（DEBUG=False）：`generic_exception_handler` 返回 `detail=None`；`AppException.to_response` 返回 `detail=None`
- **验收**: 生产模式 500 响应 body 的 detail 为 null，不含堆栈/路径

## SEC-REQ-007: 文件上传安全校验（P1）
- **来源**: CodeGraph Review #7；api-layer 03-api-contract 已定义 10MB/类型限制未实现
- **现状**: `upload.py:49-51` 直接 `await file.read()` 无校验；`upload.py:104-123` 自行 catch 异常返回 success=False，绕过全局处理器
- **描述**:
  - 校验扩展名白名单 {.pdf, .docx, .json} + MIME 白名单 + 大小 ≤10MB
  - **移除 upload.py:104-123 的 try/except 包裹**，让 ValidationError/其他异常冒泡到全局处理器（否则 413/422 无法正确返回）
  - 校验失败：扩展名/MIME → ValidationError(RESUME_003, 422)；大小 → ValidationError(RESUME_004, 413)
- **验收**: 上传 11MB 返回 413；.exe 返回 422；合法 pdf 返回 200

## SEC-REQ-008: 登录限流（P1）
- **来源**: api-layer 03-api-contract 已定义 10 req/min/IP 未实现
- **描述**: /auth/login 按 IP 限流 10 req/min（Redis 滑动窗口），超限 429
- **现状**: `auth.py` login 无 Request 参数（需新增 `request: Request` 以获取 client IP）
- **验收**: 同 IP 第 11 次返回 429
