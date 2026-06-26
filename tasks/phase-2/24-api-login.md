# T-032: FastAPI /api/v1/auth/login

## 基本信息
- **对应 Spec**: api-layer REQ-006
- **对应 AC**: AC-004, AC-005
- **依赖任务**: T-006（FastAPI 应用骨架）
- **预计工时**: 0.5 天
- **优先级**: P0

## 输入
- T-006 产出的 FastAPI 应用骨架
- T-006 产出的 `src/common/auth.py`（JWT 签发/验证，直接复用，不重新实现）
- API Layer Spec `03-api-contract.md` 中 REQ-006 的请求/响应定义
- 用户数据模型（MongoDB 中的 users collection）

## 输出
- `src/api/v1/auth.py` — 路由文件，含 `/api/v1/auth/login` 端点
- `src/api/v1/schemas/auth.py` — 请求/响应 Pydantic 模型
- ~~`src/common/security.py`~~ — **移除**：JWT 功能复用 T-006 产出的 `src/common/auth.py`，不重复实现
- `src/common/config.py` — JWT 密钥、过期时间等配置（⚠️ 增量扩展：在 T-003 产出的 config.py 基础上追加 JWT 相关配置项，禁止覆盖已有配置）
- 单元测试 `tests/api/test_auth.py`

## 实现要求

### 端点定义
```
POST /api/v1/auth/login
Content-Type: application/json
Body: {
  "username": "string",
  "password": "string"
}
Response 200:
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "uuid",
    "username": "string",
    "role": "recruiter|admin"
  }
}
```

### JWT 实现
1. 使用 `python-jose` 或 `PyJWT` 生成 JWT
2. Payload 包含：`sub`（user_id）、`role`、`exp`、`iat`
3. 密钥从环境变量 `JWT_SECRET_KEY` 读取
4. 默认过期时间 1 小时，可配置
5. 提供 `get_current_user` 依赖注入函数供其他端点复用

### 密码安全
1. 密码使用 `bcrypt` 哈希存储
2. 登录时使用 `verify_password` 比对
3. 注册时使用 `hash_password` 生成哈希

### 错误处理
- 400: 请求参数缺失
- 401: 用户名或密码错误（不暴露具体哪个错误）
- 422: 请求格式不合法

## 验收检查点

### 前置确认
- [ ] T-006 已完成并通过验收
- [ ] MongoDB 中 users collection 已存在（含至少一条测试用户）
- [ ] JWT 相关依赖已安装（`python-jose` / `PyJWT`，`passlib[bcrypt]`）

### AC 验收
- [ ] **AC-004**: 使用正确用户名密码登录，返回有效 JWT token
- [ ] **AC-005**: 使用错误密码登录返回 401；token 过期后请求受保护接口返回 401

### 代码质量
- [ ] JWT 工具函数独立于路由，可被其他模块复用
- [ ] 密码哈希不以明文形式出现在日志或响应中
- [ ] 单元测试覆盖率 ≥ 80%（含正常登录 + 错误密码 + 过期 token）
- [ ] `ruff check` / `mypy` 无报错

### Spec 一致性
- [ ] 请求/响应字段与 `03-api-contract.md` REQ-006 完全一致
- [ ] JWT payload 字段与 Spec 定义一致
- [ ] 错误响应格式符合统一错误规范

### 通过判定
- [ ] 所有 AC 验收项通过
- [ ] curl 登录测试获取 token 后可正常调用受保护接口
- [ ] `get_current_user` 可被 T-030、T-031 复用
