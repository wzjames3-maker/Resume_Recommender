<!-- Spec: api-layer (简化模块) -->
<!-- 调研决策: ✅ 直接复用 (FastAPI) -->

# 00-overview: API Layer

## 来源
PRD §4 FR-015~FR-020; 06-output-contract.md; design/ 目录

## 做什么
- 提供 RESTful API 接口（FastAPI）
- Streaming SSE 输出（推荐结果流式返回）
- JWT 认证 + RBAC 权限
- Audit Log 中间件
- CORS 配置

## 不做什么
- 不做业务逻辑（调用各模块实现）
- 不做前端 UI（由 Streamlit 负责）
- 不做 LLM 调用（由各业务模块负责）

## 技术栈
- Web 框架: FastAPI + Uvicorn
- 认证: PyJWT + FastAPI Security
- 日志: python-json-logger
- CORS: fastapi.middleware.cors

---

# 01-requirements: API Layer

| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-001 | FR-015 | POST /api/v1/chat — 聊天主接口（Streaming SSE） | P0 |
| REQ-002 | FR-010 | POST /api/v1/resumes/upload — 简历上传 | P0 |
| REQ-003 | - | GET /api/v1/conversations — 对话列表 | P1 |
| REQ-004 | - | GET /api/v1/conversations/{id} — 对话详情 | P1 |
| REQ-005 | - | DELETE /api/v1/conversations/{id} — 删除对话 | P1 |
| REQ-006 | FR-017 | POST /api/v1/auth/login — 登录获取 JWT | P1 |
| REQ-007 | FR-018 | JWT 认证中间件 | P1 |
| REQ-008 | FR-018 | RBAC 角色权限检查 | P1 |
| REQ-009 | FR-020 | Audit Log 中间件 | P0 |
| REQ-010 | - | GET /health — 健康检查 | P0 |
| REQ-011 | - | CORS 配置 | P0 |

---

# 02-data-model: API Layer

## 请求/响应模型（Pydantic）

```python
class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None

class ChatResponse(BaseModel):
    conversation_id: str
    intent: str
    content: str  # 或 Streaming chunks

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    expires_in: int
    role: str

class UploadResponse(BaseModel):
    resume_id: str
    filename: str
    status: str
    parsed_fields: dict
    warnings: list[str]

class ErrorResponse(BaseModel):
    error: dict  # {code, message, details}
```

---

# 03-api-contract: API Layer

## 端点定义

### POST /api/v1/chat
- 认证: JWT required
- 请求: ChatRequest
- 响应: Streaming SSE (text/event-stream)
- Rate Limit: 30 req/min/user

### POST /api/v1/resumes/upload
- 认证: JWT required (role: admin, hr)
- 请求: multipart/form-data (file: UploadFile)
- 响应: UploadResponse
- 限制: 文件大小 <= 10MB

### POST /api/v1/auth/login
- 认证: 无
- 请求: LoginRequest
- 响应: LoginResponse
- Rate Limit: 10 req/min/IP

### GET /health
- 认证: 无
- 响应: {"status": "ok", "version": "1.0.0"}

---

# 04-business-rules: API Layer

| ID | 规则 |
|----|------|
| RULE-001 | 所有接口（除 /health 和 /login）必须 JWT 认证 |
| RULE-002 | JWT payload 包含 user_id, role, exp |
| RULE-003 | JWT 有效期 24 小时 |
| RULE-004 | RBAC: admin 可访问全部，hr 不可删除简历，viewer 只读 |
| RULE-005 | Audit Log 记录: timestamp, user_id, path, method, status, latency_ms |
| RULE-006 | Audit Log 不记录 PII 明文 |
| RULE-007 | Streaming 响应使用 SSE (Server-Sent Events) |
| RULE-008 | 错误响应统一格式 {error: {code, message, details}} |

---

# 05-edge-cases: API Layer

| ID | 场景 | 处理 |
|----|------|------|
| EC-001 | JWT 过期 | 返回 401, error.code="TOKEN_EXPIRED" |
| EC-002 | JWT 无效 | 返回 401, error.code="INVALID_TOKEN" |
| EC-003 | 权限不足 | 返回 403, error.code="FORBIDDEN" |
| EC-004 | 请求体格式错误 | 返回 400, error.code="INVALID_INPUT" |
| EC-005 | 文件过大(>10MB) | 返回 413, error.code="FILE_TOO_LARGE" |
| EC-006 | Rate Limit 超限 | 返回 429, error.code="RATE_LIMITED" |
| EC-007 | Streaming 中 LLM 报错 | 发送 error event, 关闭 SSE |

---

# 06-acceptance: API Layer

| ID | Given | When | Then |
|----|-------|------|------|
| AC-001 | 有效 JWT | POST /api/v1/chat | 200, SSE 流开始 |
| AC-002 | 无 JWT | POST /api/v1/chat | 401 |
| AC-003 | viewer 角色 | POST /api/v1/resumes/upload | 403 |
| AC-004 | 有效用户名密码 | POST /api/v1/auth/login | 200, 返回 JWT |
| AC-005 | 任意请求 | GET /health | 200, {"status":"ok"} |
| AC-006 | 每次 API 调用 | - | Audit Log 中有记录 |

---

# 07-tech-constraints: API Layer

| 类别 | 选择 | 版本 | 理由 |
|------|------|------|------|
| Web 框架 | FastAPI | >=0.115 | 异步+Streaming |
| ASGI 服务器 | Uvicorn | >=0.34 | FastAPI 标配 |
| JWT | PyJWT | >=2.9 | 简单轻量 |
| 密码 | passlib[bcrypt] | >=1.7 | 行业标准 |
| 日志 | python-json-logger | >=3.2 | 结构化 JSON |
| 文件上传 | python-multipart | >=0.0.18 | FastAPI 依赖 |

禁用：不用 Flask（Streaming 支持弱）

---

# 08-dependencies: API Layer

## 前置
- 所有业务模块（resume-parser, intent-router, recommendation-engine, conversation-memory, resume-store）

## 后置
- frontend (Streamlit): 调用 API

## 对外接口
- HTTP API (FastAPI)
- SSE Streaming endpoint
- OpenAPI 文档自动生成 (/docs)
