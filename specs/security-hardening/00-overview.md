<!-- Spec: security-hardening (迭代模块) -->
<!-- 迭代类型: Tier M (模块增强) -->
<!-- 分支: iter/m-security-hardening -->
<!-- 日期: 2026-06-25 -->
<!-- 触发原因: CodeGraph 全项目 Review 发现 P0/P1 安全缺陷 -->
<!-- 代码核对: 2026-06-25 已逐条对照 src/ 真实实现 -->

# 00-overview: Security Hardening（安全加固迭代）

## 来源
CodeGraph 全项目 Review 报告（2026-06-25）；PRD §5 非功能需求 NFR-016（RBAC）

## 做什么
- 修复认证授权缺陷（RBAC 已定义未启用、IDOR 越权、明文密码硬编码）
- 修复密钥管理缺陷（.env 真实密钥泄露、PII 加密密钥复用 JWT、弱默认值）
- 修复 API 安全配置（CORS allow_origins=["*"]、debug 硬编码 True、文件上传无校验）
- 修复异常信息泄露（debug 模式 generic_exception_handler 返回 str(exc)）

## 不做什么
- 不重构 intent-router 双实现（单独迭代）
- 不改向量检索算法
- 不改前端交互
- 不改 conversation-memory 业务规则（RULE-001~010 不变）

## 变更范围（对应 Spec 文件）
| Spec 文件 | 变更类型 | 变更内容 |
|-----------|----------|----------|
| specs/api-layer/00-overview.md | 增补 | 04-business-rules 新增 RULE-007~012（见本迭代 04-business-rules.md） |
| specs/resume-store/00-overview.md | 增补 | PII 加密密钥分离规则（见本迭代 04-business-rules.md SEC-RULE-003） |
| specs/conversation-memory/04-business-rules.md | 增补 | 新增 RULE-011 会话归属校验（见本迭代 04-business-rules.md SEC-RULE-002） |
| specs/security-hardening/01-requirements.md | 新建 | 安全加固需求清单 |
| specs/security-hardening/04-business-rules.md | 新建 | 安全业务规则 |
| specs/security-hardening/06-acceptance.md | 新建 | 安全验收标准 |

## 现有代码基线（核对结论）
- `src/common/middleware/rbac.py`：`require_permission(*required_permissions)` 已实现，ROLE_PERMISSIONS 已定义，但 **0 个 API 端点使用它**
- `src/common/config.py`：`AppSettings.DEBUG` 默认 True；`JWTSettings.JWT_SECRET_KEY` 默认 `"your-secret-key-change-in-production"`；`MongoDBSettings.MONGODB_PASSWORD`/`RedisSettings.REDIS_PASSWORD` 默认 `"password"`；**无 PIISettings**
- `src/resume_store/encryption.py`：`_get_key` 复用 `settings.jwt.JWT_SECRET_KEY` + sha256 派生，`getattr` 兜底 `"default-secret-key"`
- `src/api/main.py:21-27`：`allow_origins=["*"]` + `allow_credentials=True`；`app.state.debug = True` 硬编码
- `src/api/v1/upload.py:104-123`：自行 catch ValidationError/Exception 返回 `success=False`，**绕过全局异常处理器**
- `src/api/v1/conversations.py:77-128`：get/delete 取了 user_id 但**未校验 session.user_id 归属**
- `src/api/v1/auth.py:39-55`：`USERS_DB` 硬编码明文密码
- `src/common/errors.py`：`generic_exception_handler` debug 时返回 `str(exc)`；`AppException.to_response` debug 时返回 `self.error_detail`
- `.env`：含真实 `sk-` 密钥；`.env.example`：已用占位符但 env 名与 config 字段不一致（`APP_DEBUG` vs `DEBUG`）
- 项目无 `.git`、无 `.gitignore`

## 冻结点
本迭代 spec 经 Phase 5 评审冻结后为 v1.1-security 基线。
