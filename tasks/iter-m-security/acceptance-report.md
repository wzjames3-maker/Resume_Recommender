# 集成验收报告：iter/m-security-hardening

## 基本信息
- **迭代类型**: Tier M（模块增强）
- **分支**: iter/m-security-hardening
- **完成日期**: 2026-06-25
- **测试结果**: 66 passed, 0 failed

## 逐项验收

### AC-SEC-001: RBAC 权限强制
- [x] viewer token POST /resumes/upload → 403 (test: test_viewer_upload_denied)
- [x] hr token POST /resumes/upload → 400/422 (permission passed, missing file body)
- [x] viewer token POST /chat → 403 (test: test_viewer_chat_denied)
- [x] viewer token GET /conversations → 200 (test: test_viewer_list_allowed)
- [x] viewer token DELETE /conversations/{id} → 403 (test: test_viewer_delete_denied)
- [x] public /health → 200 (test: test_health_no_auth)
- [x] public /login → accessible (test: test_login_no_auth)

### AC-SEC-002: IDOR 越权防护
- [x] user A token GET /conversations/{non-existent} → 404 + CONV_001
- [x] user A token DELETE /conversations/{non-existent} → 404 + CONV_001
- [x] Non-owner returns 404 (never 403) to prevent enumeration
- [x] conversations routes use ResourceNotFoundError not raw HTTPException
- [x] repository.list() already has user_id isolation (regression confirmed)

### AC-SEC-003: 密钥分离
- [x] PIISettings exists with PII_ENCRYPTION_KEY (Field: required)
- [x] encryption.py reads settings.pii.PII_ENCRYPTION_KEY directly
- [x] No sha256, getattr, or settings.jwt references in encryption.py
- [x] JWT_SECRET_KEY/MONGODB_PASSWORD/REDIS_PASSWORD defaults → required
- [x] LLM_API_KEY/EMBEDDING_API_KEY keep empty string defaults
- [x] Migration script at scripts/migrate_pii_key.py
- [x] 6 encryption tests pass

### AC-SEC-004: .env 忽略
- [x] .gitignore exists and covers .env, __pycache__, *.log, .coverage, screenshot_*.png
- [x] git check-ignore .env → .env
- [x] .env.example has no sk- real keys
- [x] .env.example env names aligned with config fields (DEBUG not APP_DEBUG)
- [x] .env.example has PII_ENCRYPTION_KEY= placeholder
- [ ] ⚠️ 人工待办: revoke old LLM/OCR/Embedding/Reranker API Keys

### AC-SEC-005: 密码哈希
- [x] user_store.py with passlib bcrypt
- [x] auth.py uses get_user_by_username + verify_password
- [x] No USERS_DB dict or plaintext comparison in auth.py
- [x] passlib[bcrypt] added to pyproject.toml
- [x] 14 auth unit tests pass (regression confirmed)

### AC-SEC-006: CORS 与 debug
- [x] main.py no longer has allow_origins=["*"]
- [x] CORS origins from settings.app.CORS_ORIGINS
- [x] app.state.debug from settings.app.DEBUG (default False)
- [x] No hardcoded debug=True

### AC-SEC-007: 文件上传校验
- [x] 11MB → 413 (test: test_size_exceeded_rejected)
- [x] .exe → 422 (test: test_exe_extension_rejected)
- [x] PDF with wrong MIME → 422 (test: test_wrong_mime_rejected)
- [x] Validation happens before MD5 check
- [x] No try/except swallowing exceptions in upload.py

### AC-SEC-008: 登录限流
- [x] 10 requests within limit pass
- [x] 11th request blocked
- [x] Different keys independent
- [x] 3 rate limiter tests pass

### 回归测试
- [x] test_auth.py: 14/14 pass
- [x] test_rbac.py: 25/25 pass
- [x] test_encryption.py: 6/6 pass
- [x] test_rbac_enforcement.py: 8/8 pass
- [x] test_idor.py: 4/4 pass
- [x] test_upload_safety.py: 4/4 pass
- [x] test_rate_limiter.py: 3/3 pass
- [x] test_errors.py: confirmed existing tests compatible

## 汇总
| AC | 状态 | 测试数 |
|----|------|--------|
| AC-SEC-001 | ✅ | 8 |
| AC-SEC-002 | ✅ | 4 |
| AC-SEC-003 | ✅ | 6 |
| AC-SEC-004 | ✅* | - |
| AC-SEC-005 | ✅ | 14+1 |
| AC-SEC-006 | ✅ | - |
| AC-SEC-007 | ✅ | 4 |
| AC-SEC-008 | ✅ | 3 |
| 回归 | ✅ | 25+14=39 |
| **总计** | **66 passed** | |

*AC-SEC-004: .env 已忽略；人工吊销密钥待执行

## 修改文件清单
| 文件 | 修改类型 |
|------|----------|
| .gitignore | 新建 |
| .env.example | 修正 |
| .env | 追加 PII_ENCRYPTION_KEY |
| CHANGELOG.md | 追加 v0.2.0-security |
| src/common/config.py | 新增 PIISettings/CORS_ORIGINS；密钥必填化；TEST env |
| src/common/user_store.py | 新建（bcrypt 用户管理） |
| src/common/rate_limiter.py | 新建（限流器） |
| src/resume_store/encryption.py | _get_key 改读 PII_ENCRYPTION_KEY；新增 reset() |
| src/api/main.py | CORS+debug 配置化 |
| src/api/v1/auth.py | bcrypt 验证；移除 USERS_DB；限流 |
| src/api/v1/upload.py | RBAC+文件校验；移除异常吞没 |
| src/api/v1/chat.py | RBAC 权限 |
| src/api/v1/conversations.py | RBAC+IDOR 归属校验 |
| pyproject.toml | 新增 passlib[bcrypt] |
| scripts/migrate_pii_key.py | 新建 |
| tests/security/test_rbac_enforcement.py | 新建 |
| tests/security/test_idor.py | 新建 |
| tests/security/test_upload_safety.py | 新建 |
| tests/unit/test_encryption.py | 新建 |
| tests/unit/test_rate_limiter.py | 新建 |

## 未完成事项（人工）
- [ ] 吊销 .env 中泄露的 SenseNova API Key（LLM/OCR/Embedding/Reranker）
- [ ] 运行 scripts/migrate_pii_key.py 迁移存量 PII 密文（如有）
- [ ] 运行 python -c "from passlib.context import CryptContext; ctx=CryptContext(schemes=['bcrypt']); print(ctx.hash('your_password'))" 生成新管理员密码
