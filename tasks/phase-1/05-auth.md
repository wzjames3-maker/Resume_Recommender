# T-006: 认证中间件

## 基本信息
- 对应 Spec: tech-decision.md 决策项（认证方案）、specs/api-layer/00-overview.md (RULE-001~004)
- 对应 AC: PRD 中认证相关用例
- 依赖: T-002, T-004
- 预计工时: 1 天

## 输入
- docs/tech-decision.md
- docs/PRD.md（认证与权限相关用例）
- src/common/ 包结构（来自 T-002）
- src/common/errors.py（来自 T-004）
- src/api/ FastAPI 应用入口（来自 T-002）

## 输出
- src/common/auth.py
- src/common/middleware/rbac.py
- tests/unit/test_auth.py
- tests/unit/test_rbac.py

## 实现要求
1. 创建 `src/common/auth.py`：
   - JWT 签发函数 `create_access_token(data: dict, expires_delta: Optional[timedelta]) -> str`
   - JWT 验证函数 `decode_access_token(token: str) -> dict`
   - 使用 `PyJWT` 库
   - 算法配置化（默认 HS256），通过 `AuthSettings` 读取
   - Token payload 包含：sub (user_id), role, exp, iat, jti
   - Token 过期抛出 `AuthenticationError`
2. 创建 `src/common/middleware/rbac.py`：
   - RBAC 权限检查装饰器/依赖项
   - 角色定义：admin, hr, viewer（对齐 PRD 权限矩阵）
   - `require_role(*roles: str)` — FastAPI Depends 可用的依赖工厂
   - 权限不足抛出 `AuthorizationError`
3. 创建 FastAPI 依赖注入：
   - `get_current_user(token: str = Depends(oauth2_scheme))` — 解析当前用户
   - `require_admin = require_role("admin")`
   - `require_hr = require_role("admin", "hr")`
4. 编写单元测试：
   - JWT 签发与验证往返测试
   - Token 过期测试
   - RBAC 权限通过与拒绝测试
   - 无效 Token 测试（格式错误、签名错误）

## 验收检查点

### 前置确认
- [ ] T-002 已完成（项目骨架存在）
- [ ] T-004 已完成（错误码体系存在）
- [ ] docs/PRD.md 已读取（权限矩阵部分）

### AC 验收
- [ ] 签发的 JWT 能正确解码验证
- [ ] 过期 Token 返回 401 + AuthenticationError
- [ ] RBAC 权限不足返回 403 + AuthorizationError
- [ ] `get_current_user` 能从 header 中提取用户信息

### 代码质量
- [ ] 密钥从配置读取，不硬编码
- [ ] 所有异常使用统一错误码体系
- [ ] 单元测试全部通过

### Spec 一致性
- [ ] 角色定义与 PRD 权限矩阵一致
- [ ] JWT 算法与 tech-decision.md 一致
- [ ] Token payload 字段完整

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry < 3 → 修复 | retry = 3 → BLOCKED
