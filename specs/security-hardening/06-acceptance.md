<!-- Spec: security-hardening -->
<!-- Spec Layer: 06 - Acceptance -->
<!-- 迭代类型: Tier M -->
<!-- 代码核对: 2026-06-25 -->

# 安全加固验收标准

## AC-SEC-001: RBAC 权限强制（对应 SEC-REQ-001 / SEC-RULE-001）
- [ ] viewer token 调用 `POST /api/v1/resumes/upload` 返回 403 + code=AUTH_002
- [ ] hr token 调用 `POST /api/v1/resumes/upload` 返回 200
- [ ] viewer token 调用 `POST /api/v1/chat` 返回 403 + AUTH_002（viewer 无 conversation:create）
- [ ] admin token 调用 `DELETE /api/v1/conversations/{id}` 返回 200
- [ ] viewer token 调用 `DELETE /api/v1/conversations/{id}` 返回 403（viewer 无 conversation:delete）
- [ ] viewer token 调用 `GET /api/v1/conversations` 返回 200（viewer 有 conversation:read）
- [ ] OpenAPI /docs 各端点显示 lock 图标与所需权限

## AC-SEC-002: 资源归属校验（对应 SEC-REQ-002 / SEC-RULE-002）
- [ ] 用户 A token GET `/conversations/{B的id}` 返回 404 + code=CONV_001（非 200/403）
- [ ] 用户 A token DELETE `/conversations/{B的id}` 返回 404 + CONV_001
- [ ] admin token GET `/conversations/{B的id}` 返回 200（豁免）
- [ ] 用户 A token GET `/conversations/{自己的id}` 返回 200
- [ ] 不存在的 conversation_id 返回 404 + CONV_001
- [ ] conversations 路由不再使用裸 `HTTPException`，改用 `ResourceNotFoundError(CONV_001)`
- [ ] 简历列表（repository.list）已有 user_id 隔离，回归通过

## AC-SEC-003: 密钥分离（对应 SEC-REQ-003 / SEC-RULE-003/004）
- [ ] `config.py` 新增 `PIISettings.PII_ENCRYPTION_KEY: str = Field(...)`，`Settings` 聚合 `pii`
- [ ] `encryption.py._get_key` 读 `settings.pii.PII_ENCRYPTION_KEY`，不再 import/引用 `settings.jwt`
- [ ] 删除 `getattr(..., "default-secret-key")` 兜底与 sha256 派生
- [ ] `JWT_SECRET_KEY`/`MONGODB_PASSWORD`/`REDIS_PASSWORD` Field default 为 `...`
- [ ] `LLM_API_KEY`/`EMBEDDING_API_KEY` 保持空串默认（不 fail-fast）
- [ ] 缺失 PII_ENCRYPTION_KEY 时 `get_settings()` 抛 ValidationError
- [ ] 迁移脚本：旧密文（sha256 派生 key 加密）→ 新 key 重新加密，往返验证通过

## AC-SEC-004: .env 版本控制（对应 SEC-REQ-004）
- [ ] `.gitignore` 存在且包含 `.env`、`__pycache__`、`*.log`、`.coverage`、`screenshot_*.png`、`.codegraph/`
- [ ] `git check-ignore .env` 返回 `.env`
- [ ] `.env.example` 无 `sk-` 真实 key
- [ ] `.env.example` env 名对齐 config 字段（`DEBUG` 而非 `APP_DEBUG`）
- [ ] `.env.example` 含 `PII_ENCRYPTION_KEY=` 占位
- [ ] 旧 LLM/OCR/Embedding/Reranker API Key 已吊销（人工签字确认）

## AC-SEC-005: 密码哈希（对应 SEC-REQ-005）
- [ ] MongoDB `users` collection 存在
- [ ] password_hash 字段以 `$2b$` 开头（bcrypt）
- [ ] `auth.py` 无 USERS_DB 字典、无明文比对
- [ ] `auth.py` login 改用 `user_store.find_by_username` + `pwd_context.verify`
- [ ] `init_users.py` 创建用户并哈希密码
- [ ] `pyproject.toml` 含 `passlib[bcrypt]` 依赖

## AC-SEC-006: CORS 与 debug（对应 SEC-REQ-006 / SEC-RULE-005/007）
- [ ] `main.py` 无 `allow_origins=["*"]`
- [ ] `allow_origins` 来自 `settings.app.CORS_ORIGINS`
- [ ] `main.py` 无 `app.state.debug = True` 硬编码，改读 `settings.app.DEBUG`
- [ ] `DEBUG` 未设置时 `app.state.debug == False`（AppSettings.DEBUG 默认改为 False）
- [ ] 生产模式 GET /test-error 返回 `detail: null`
- [ ] 生产模式 500 响应不含文件路径/堆栈字符串

## AC-SEC-007: 文件上传校验（对应 SEC-REQ-007 / SEC-RULE-006）
- [ ] 上传 11MB PDF 返回 413 + code=RESUME_004
- [ ] 上传 .exe 返回 422 + RESUME_003
- [ ] 上传 .pdf 但 MIME=image/jpeg 返回 422 + RESUME_003
- [ ] 上传合法 .pdf ≤10MB 返回 200
- [ ] `upload.py` 移除 104-123 行 try/except 包裹，异常冒泡到全局处理器
- [ ] 校验在 MD5 去重之前执行

## AC-SEC-008: 登录限流（对应 SEC-REQ-008 / SEC-RULE-008）
- [ ] `auth.py` login 新增 `request: Request` 参数
- [ ] 同 IP 连续 10 次 /auth/login 正常响应
- [ ] 同 IP 第 11 次返回 429 + SYS_004
- [ ] 限流在密码校验之前执行
- [ ] 60s 后计数重置可再次登录

## 回归测试
- [ ] 现有 `tests/unit/test_auth.py` 全部通过
- [ ] 现有 `tests/unit/test_rbac.py` 全部通过
- [ ] 现有 `tests/unit/test_errors.py` 全部通过
- [ ] 新增 `tests/security/test_rbac_enforcement.py` 通过
- [ ] 新增 `tests/security/test_idor.py` 通过
- [ ] 新增 `tests/security/test_upload_safety.py` 通过
- [ ] `pytest tests/` 全量回归无新增失败
