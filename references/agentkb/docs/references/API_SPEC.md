# MaxKB 复刻 — REST API 完整规范

> 版本：v1.0
> 后端框架：FastAPI + Pydantic v2
> 适用对象：后端实现、前端联调、测试用例编写

---

## 目录

1. [通用约定](#1-通用约定)
2. [错误码表](#2-错误码表)
3. [完整端点列表](#3-完整端点列表)
4. [每个端点的详细 Schema](#4-每个端点的详细-schema)
5. [SSE 流式响应格式](#5-sse-流式响应格式)
6. [认证流程时序图](#6-认证流程时序图)
7. [多租户权限矩阵](#7-多租户权限矩阵)

---

## 1. 通用约定

### 1.1 Base URL

```
https://{host}/api/v1
```

本地开发环境：`http://localhost:8000/api/v1`

### 1.2 认证方式

除 `POST /auth/register`、`POST /auth/login`、`POST /auth/refresh`、`GET /admin/health`、`GET /admin/metrics` 外，所有端点均需在请求头携带 Bearer Token：

```
Authorization: Bearer <access_token>
```

- `access_token`：JWT，有效期 30 分钟，载荷包含 `sub`（user_id）、`exp`、`iat`
- `refresh_token`：不透明字符串（opaque token），有效期 7 天，仅用于换取新的 access_token
- Token 过期返回 `401 TOKEN_EXPIRED`，客户端应自动调用 `/auth/refresh` 续签

### 1.3 Content-Type

| 场景 | Content-Type |
|------|--------------|
| 普通 JSON 请求/响应 | `application/json` |
| 文件上传（文档创建） | `multipart/form-data` |
| SSE 流式响应 | `text/event-stream` |
| Prometheus 指标 | `text/plain; version=0.0.4` |

### 1.4 错误响应格式

所有非 2xx 响应统一为如下结构：

```json
{
  "code": "VALIDATION_ERROR",
  "message": "chunk_size 必须在 64 到 8192 之间",
  "detail": {
    "field": "chunk_size",
    "constraint": "ge=64,le=8192",
    "received": 50
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | string | 机器可读错误码，见第 2 节 |
| `message` | string | 人类可读错误描述 |
| `detail` | object \| null | 附加上下文（字段名、约束、冲突资源等），可为 null |

### 1.5 分页约定

列表端点统一支持查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码，从 1 开始 |
| `page_size` | int | 20 | 每页条数，最大 100 |

分页响应统一包裹结构：

```json
{
  "total": 137,
  "page": 1,
  "page_size": 20,
  "items": [ ... ]
}
```

### 1.6 限流

- 所有响应携带 `X-RateLimit-Remaining` 头（当前窗口剩余请求数）
- 附带 `X-RateLimit-Limit`（窗口上限）与 `X-RateLimit-Reset`（窗口重置的 Unix 时间戳）
- 默认策略：每用户每分钟 120 次；`/chat` 端点每用户每分钟 20 次
- 超限返回 `429 RATE_LIMITED`，并携带 `Retry-After` 头（秒）

### 1.7 时间格式

所有时间字段使用 UTC ISO 8601 格式：`2026-08-04T09:30:00Z`

### 1.8 ID 类型

- 用户、工作区、知识库、会话、消息：`int64`（自增主键）
- 文档、Chunk：`int64`
- 响应 JSON 中序列化为 number（前端注意 JS 精度问题，超过 2^53 时后端改为 string，当前规模无需处理）

### 1.9 CORS

- 生产环境：前端与 API 同域部署，由 Nginx 将 `/api` 反向代理到后端，浏览器视角无跨域，无需 CORS
- 开发环境：Vite dev server 通过 `server.proxy` 将 `/api` 请求转发至 `http://localhost:8000`，同样无跨域
- 因此后端默认不启用 CORS 中间件；如未来确有跨域需求再单独配置

---

## 2. 错误码表

| HTTP Status | Code | 含义 | 典型触发场景 |
|-------------|------|------|--------------|
| 400 | `VALIDATION_ERROR` | 请求参数校验失败 | 字段缺失、类型错误、超出取值范围 |
| 401 | `UNAUTHORIZED` | 未认证或凭证无效 | 缺少 Authorization 头、token 非法、邮箱密码错误 |
| 401 | `TOKEN_EXPIRED` | access_token 已过期 | JWT exp 校验失败，客户端应走 refresh 流程 |
| 403 | `FORBIDDEN` | 已认证但无权限 | member 尝试删除工作区、跨工作区访问资源 |
| 404 | `NOT_FOUND` | 资源不存在 | ID 不存在，或当前用户无权可见（防探测统一返回 404） |
| 409 | `CONFLICT` | 资源冲突 | 邮箱已注册、工作区内知识库重名、邀请已是成员的用户 |
| 413 | `FILE_TOO_LARGE` | 上传文件超过限制 | 单文件超过 50 MB |
| 429 | `RATE_LIMITED` | 触发限流 | 超出每分钟请求配额 |
| 429 | `QUOTA_EXCEEDED` | 工作区月度 token 配额耗尽 | chat 请求时工作区当月 token 用量已达上限 |
| 500 | `INTERNAL_ERROR` | 服务器内部错误 | 未捕获异常，响应不泄露堆栈，仅返回 request_id |

补充说明：

- 所有 5xx 响应的 `detail` 中包含 `request_id`，用于日志排查
- 404 与 403 的边界：当资源存在但用户不属于其所属工作区时，统一返回 `404 NOT_FOUND`，避免泄露资源存在性

---

## 3. 完整端点列表

共 33 个端点。

### 3.1 Auth（4 个）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/auth/register` | 用户注册 | 否 |
| POST | `/auth/login` | 登录，签发令牌对 | 否 |
| POST | `/auth/refresh` | 用 refresh_token 换新 access_token | 否 |
| POST | `/auth/logout` | 注销 refresh_token | 是 |

### 3.2 Users（2 个）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/users/me` | 获取当前用户信息 | 是 |
| PUT | `/users/me` | 更新当前用户昵称 | 是 |

### 3.3 Workspaces（8 个）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/workspaces` | 创建工作区（创建者自动成为 owner） | 是 |
| GET | `/workspaces` | 列出当前用户所在的全部工作区 | 是 |
| GET | `/workspaces/{id}` | 工作区详情 + 成员列表 | 是 |
| DELETE | `/workspaces/{id}` | 删除工作区（仅 owner） | 是 |
| POST | `/workspaces/{ws_id}/members` | 邀请成员加入工作区 | 是 |
| PATCH | `/workspaces/{ws_id}/members/{user_id}` | 修改成员角色 | 是 |
| DELETE | `/workspaces/{ws_id}/members/{user_id}` | 将成员移出工作区 | 是 |
| GET | `/workspaces/{ws_id}/usage` | 工作区本月 token 用量与配额 | 是 |

### 3.4 Knowledge Bases（5 个）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/workspaces/{ws_id}/knowledge-bases` | 在指定工作区创建知识库 | 是 |
| GET | `/workspaces/{ws_id}/knowledge-bases` | 列出工作区下的知识库 | 是 |
| GET | `/knowledge-bases/{id}` | 知识库详情（含 doc_count、chunk_count） | 是 |
| PUT | `/knowledge-bases/{id}` | 更新知识库配置 | 是 |
| DELETE | `/knowledge-bases/{id}` | 删除知识库（级联删除文档、分块、会话与消息） | 是 |

### 3.5 Documents（6 个）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/knowledge-bases/{kb_id}/documents` | 上传文档（multipart），触发异步解析 | 是 |
| GET | `/knowledge-bases/{kb_id}/documents` | 列出知识库下的文档及状态 | 是 |
| GET | `/documents/{id}` | 文档详情（状态、分块数、错误信息） | 是 |
| GET | `/documents/{id}/chunks` | 分页查看文档的分块 | 是 |
| DELETE | `/documents/{id}` | 删除文档（级联删除分块） | 是 |
| POST | `/documents/{id}/retry` | 重新触发失败的解析任务 | 是 |

### 3.6 Chat（5 个）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/chat` | 提问，支持 SSE 流式返回 | 是 |
| POST | `/conversations` | 创建会话 | 是 |
| GET | `/conversations` | 按知识库筛选会话列表 | 是 |
| GET | `/conversations/{id}/messages` | 会话消息历史 | 是 |
| DELETE | `/conversations/{id}` | 删除会话 | 是 |

### 3.7 Admin（3 个）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/admin/usage` | 按日期区间统计 token 用量 | 是（仅平台管理员） |
| GET | `/admin/health` | 健康检查（db / redis / celery） | 否 |
| GET | `/admin/metrics` | Prometheus 指标 | 否（内网暴露） |

---

## 4. 每个端点的详细 Schema

> Pydantic 模型使用 v2 语法。`...` 表示必填字段。

---

### 4.1 Auth

#### 4.1.1 POST /auth/register

注册新用户。

**请求体 `RegisterRequest`：**

```python
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=64)
    nickname: str = Field(..., min_length=1, max_length=32)
```

**响应体 `RegisterResponse`（201）：**

```python
class RegisterResponse(BaseModel):
    user_id: int
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 邮箱格式非法 / 密码少于 8 位 / 昵称为空 |
| 409 | `CONFLICT` | 邮箱已注册 |
| 429 | `RATE_LIMITED` | 注册接口限流（每 IP 每分钟 5 次） |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "s3cretPass!", "nickname": "Alice"}'
```

**响应示例：**

```json
{
  "user_id": 1001
}
```

---

#### 4.1.2 POST /auth/login

邮箱密码登录，返回令牌对。

**请求体 `LoginRequest`：**

```python
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
```

**响应体 `LoginResponse`（200）：**

```python
class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # 固定值 "bearer"
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 字段缺失 |
| 401 | `UNAUTHORIZED` | 邮箱或密码错误（不区分"用户不存在"与"密码错误"） |
| 429 | `RATE_LIMITED` | 登录接口限流（每 IP 每分钟 10 次） |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "s3cretPass!"}'
```

**响应示例：**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMDAxIiwiZXhwIjoxNzU0MzAwMDAwfQ.xxx",
  "refresh_token": "rt_8f3a2b1c9d4e5f6a7b8c",
  "token_type": "bearer"
}
```

---

#### 4.1.3 POST /auth/refresh

用 refresh_token 换取新的 access_token。refresh_token 不轮换：在注销或过期（7 天）之前始终保持有效，可重复使用；每次 refresh 仅签发新的 access_token。

**请求体 `RefreshRequest`：**

```python
class RefreshRequest(BaseModel):
    refresh_token: str
```

**响应体 `RefreshResponse`（200）：**

```python
class RefreshResponse(BaseModel):
    access_token: str
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 字段缺失 |
| 401 | `UNAUTHORIZED` | refresh_token 无效、已被注销或已过期 |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "rt_8f3a2b1c9d4e5f6a7b8c"}'
```

**响应示例：**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMDAxIiwiZXhwIjoxNzU0MzAxODAwfQ.yyy"
}
```

---

#### 4.1.4 POST /auth/logout

注销当前会话的 refresh_token（access_token 自然过期）。接口幂等：无论 refresh_token 是否存在、是否已注销，均返回 204。

**请求体 `LogoutRequest`：**

```python
class LogoutRequest(BaseModel):
    refresh_token: str
```

**响应：`204 No Content`，无响应体。**

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | 未携带有效 access_token |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "rt_8f3a2b1c9d4e5f6a7b8c"}' \
  -w "%{http_code}"
# 输出：204
```

---

### 4.2 Users

#### 4.2.1 GET /users/me

获取当前登录用户信息。

**请求：无请求体。**

**响应体 `UserOut`（200）：**

```python
class UserOut(BaseModel):
    id: int
    email: EmailStr
    nickname: str
    created_at: datetime
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` / `TOKEN_EXPIRED` | token 缺失、非法或过期 |

**curl 示例：**

```bash
curl http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "id": 1001,
  "email": "alice@example.com",
  "nickname": "Alice",
  "created_at": "2026-08-01T02:15:30Z"
}
```

---

#### 4.2.2 PUT /users/me

更新当前用户昵称。

**请求体 `UserUpdateRequest`：**

```python
class UserUpdateRequest(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=32)
```

**响应体 `UserOut`（200）：** 同 4.2.1，返回更新后的完整用户对象。

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 昵称为空或超长 |
| 401 | `UNAUTHORIZED` | token 无效 |

**curl 示例：**

```bash
curl -X PUT http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"nickname": "Alice Wang"}'
```

**响应示例：**

```json
{
  "id": 1001,
  "email": "alice@example.com",
  "nickname": "Alice Wang",
  "created_at": "2026-08-01T02:15:30Z"
}
```

---

### 4.3 Workspaces

#### 4.3.1 POST /workspaces

创建工作区，创建者自动成为 `owner`。

**请求体 `WorkspaceCreateRequest`：**

```python
class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
```

**响应体 `WorkspaceOut`（201）：**

```python
class WorkspaceOut(BaseModel):
    id: int
    name: str
    role: str          # 当前用户在该工作区的角色：owner | admin | member
    created_at: datetime
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 名称为空或超长 |
| 401 | `UNAUTHORIZED` | token 无效 |
| 409 | `CONFLICT` | 当前用户已有同名工作区 |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "研发团队"}'
```

**响应示例：**

```json
{
  "id": 201,
  "name": "研发团队",
  "role": "owner",
  "created_at": "2026-08-04T09:00:00Z"
}
```

---

#### 4.3.2 GET /workspaces

列出当前用户加入的全部工作区。

**请求：无请求体，无分页（单用户工作区数量有限，直接全量返回）。**

**响应体（200）：**

```python
class WorkspaceListResponse(BaseModel):
    items: list[WorkspaceOut]
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |

**curl 示例：**

```bash
curl http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "items": [
    {"id": 201, "name": "研发团队", "role": "owner", "created_at": "2026-08-04T09:00:00Z"},
    {"id": 205, "name": "市场部", "role": "member", "created_at": "2026-08-02T03:20:11Z"}
  ]
}
```

---

#### 4.3.3 GET /workspaces/{id}

工作区详情，含成员列表。仅工作区成员可访问。

**路径参数：** `id: int` — 工作区 ID

**响应体 `WorkspaceDetailOut`（200）：**

```python
class WorkspaceMemberOut(BaseModel):
    user_id: int
    nickname: str
    email: EmailStr
    role: str          # owner | admin | member
    joined_at: datetime

class WorkspaceDetailOut(BaseModel):
    id: int
    name: str
    role: str                        # 当前用户的角色
    created_at: datetime
    members: list[WorkspaceMemberOut]
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 工作区不存在，或当前用户不是成员 |

**curl 示例：**

```bash
curl http://localhost:8000/api/v1/workspaces/201 \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "id": 201,
  "name": "研发团队",
  "role": "owner",
  "created_at": "2026-08-04T09:00:00Z",
  "members": [
    {"user_id": 1001, "nickname": "Alice Wang", "email": "alice@example.com", "role": "owner", "joined_at": "2026-08-04T09:00:00Z"},
    {"user_id": 1002, "nickname": "Bob", "email": "bob@example.com", "role": "admin", "joined_at": "2026-08-04T09:30:00Z"},
    {"user_id": 1003, "nickname": "Carol", "email": "carol@example.com", "role": "member", "joined_at": "2026-08-04T10:00:00Z"}
  ]
}
```

---

#### 4.3.4 DELETE /workspaces/{id}

删除工作区。仅 `owner` 可操作。级联删除工作区下所有知识库、文档、分块、会话与消息。

**路径参数：** `id: int`

**响应：`204 No Content`，无响应体。**

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 当前用户不是 owner |
| 404 | `NOT_FOUND` | 工作区不存在或非成员 |

**curl 示例：**

```bash
curl -X DELETE http://localhost:8000/api/v1/workspaces/201 \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -w "%{http_code}"
# 输出：204
```

---

#### 4.3.5 POST /workspaces/{ws_id}/members

邀请已注册用户加入工作区。`admin` 及以上角色可操作。

**路径参数：** `ws_id: int` — 工作区 ID

**请求体 `MemberInviteRequest`：**

```python
class MemberInviteRequest(BaseModel):
    email: EmailStr
    role: str = Field(..., pattern=r"^(admin|member)$")  # 不允许直接邀请为 owner
```

**响应体 `WorkspaceMemberOut`（201）：** 同 4.3.3 中的定义。

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | email 格式非法 / role 取值非法 |
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 当前用户角色为 member |
| 404 | `NOT_FOUND` | 工作区不存在或非成员 / 邮箱对应账号不存在 |
| 409 | `CONFLICT` | 该用户已是工作区成员 |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/workspaces/201/members \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "carol@example.com", "role": "member"}'
```

**响应示例：**

```json
{
  "user_id": 1003,
  "nickname": "Carol",
  "email": "carol@example.com",
  "role": "member",
  "joined_at": "2026-08-04T10:00:00Z"
}
```

---

#### 4.3.6 PATCH /workspaces/{ws_id}/members/{user_id}

修改成员角色。`admin` 及以上可操作。不可将成员设为 owner，也不可修改 owner 的角色。

**路径参数：** `ws_id: int` — 工作区 ID、`user_id: int` — 目标成员的用户 ID

**请求体 `MemberRoleUpdateRequest`：**

```python
class MemberRoleUpdateRequest(BaseModel):
    role: str = Field(..., pattern=r"^(admin|member)$")
```

**响应体 `WorkspaceMemberOut`（200）：** 同 4.3.3 中的定义，返回更新后的成员信息。

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | role 取值非法 |
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 当前用户角色为 member |
| 404 | `NOT_FOUND` | 工作区不存在或非成员 / 目标用户不是工作区成员 |
| 409 | `CONFLICT` | 目标成员是 owner，角色不可修改 |

**curl 示例：**

```bash
curl -X PATCH http://localhost:8000/api/v1/workspaces/201/members/1003 \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin"}'
```

**响应示例：**

```json
{
  "user_id": 1003,
  "nickname": "Carol",
  "email": "carol@example.com",
  "role": "admin",
  "joined_at": "2026-08-04T10:00:00Z"
}
```

---

#### 4.3.7 DELETE /workspaces/{ws_id}/members/{user_id}

将成员移出工作区。`admin` 及以上可操作。不可移除 owner。

**路径参数：** `ws_id: int` — 工作区 ID、`user_id: int` — 目标成员的用户 ID

**响应：`204 No Content`，无响应体。**

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 当前用户角色为 member |
| 404 | `NOT_FOUND` | 工作区不存在或非成员 / 目标用户不是工作区成员 |
| 409 | `CONFLICT` | 目标成员是 owner，不可移除 |

**curl 示例：**

```bash
curl -X DELETE http://localhost:8000/api/v1/workspaces/201/members/1003 \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -w "%{http_code}"
# 输出：204
```

---

#### 4.3.8 GET /workspaces/{ws_id}/usage

查询工作区本月 token 用量与配额。工作区成员均可访问。

**路径参数：** `ws_id: int` — 工作区 ID

**响应体 `WorkspaceUsageOut`（200）：**

```python
class WorkspaceUsageOut(BaseModel):
    tokens_used_this_month: int
    monthly_limit: int
    remaining: int
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 工作区不存在或非成员 |

**curl 示例：**

```bash
curl http://localhost:8000/api/v1/workspaces/201/usage \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "tokens_used_this_month": 47500,
  "monthly_limit": 1000000,
  "remaining": 952500
}
```

---

### 4.4 Knowledge Bases

#### 4.4.1 POST /workspaces/{ws_id}/knowledge-bases

在指定工作区创建知识库。`admin` 及以上角色可操作。

**路径参数：** `ws_id: int` — 工作区 ID

**请求体 `KnowledgeBaseCreateRequest`：**

```python
class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field("", max_length=512)
    embedding_model: str = Field("bge-m3", max_length=128)
    chunk_size: int = Field(512, ge=64, le=8192)
    chunk_overlap: int = Field(64, ge=0)

    @model_validator(mode="after")
    def check_overlap(self) -> "KnowledgeBaseCreateRequest":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        return self
```

> 注意：默认模型 `bge-m3` 的向量维度固定 1024（对应数据库 `embedding vector(1024)`），更换模型时必须确保维度匹配。

**响应体 `KnowledgeBaseOut`（201）：**

```python
class KnowledgeBaseOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    description: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    created_at: datetime
    updated_at: datetime
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 参数越界 / overlap ≥ chunk_size |
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 当前用户在该工作区角色为 member |
| 404 | `NOT_FOUND` | 工作区不存在或非成员 |
| 409 | `CONFLICT` | 同一工作区内知识库重名 |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/workspaces/201/knowledge-bases \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "产品手册",
    "description": "产品使用与 FAQ",
    "embedding_model": "bge-m3",
    "chunk_size": 512,
    "chunk_overlap": 64
  }'
```

**响应示例：**

```json
{
  "id": 301,
  "workspace_id": 201,
  "name": "产品手册",
  "description": "产品使用与 FAQ",
  "embedding_model": "bge-m3",
  "chunk_size": 512,
  "chunk_overlap": 64,
  "created_at": "2026-08-04T09:10:00Z",
  "updated_at": "2026-08-04T09:10:00Z"
}
```

---

#### 4.4.2 GET /workspaces/{ws_id}/knowledge-bases

列出工作区下的知识库，支持分页。

**路径参数：** `ws_id: int`

**查询参数：** `page`、`page_size`（见 1.5）

**响应体（200）：**

```python
class KnowledgeBaseListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[KnowledgeBaseOut]
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 工作区不存在或非成员 |

**curl 示例：**

```bash
curl "http://localhost:8000/api/v1/workspaces/201/knowledge-bases?page=1&page_size=20" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "total": 2,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": 301,
      "workspace_id": 201,
      "name": "产品手册",
      "description": "产品使用与 FAQ",
      "embedding_model": "bge-m3",
      "chunk_size": 512,
      "chunk_overlap": 64,
      "created_at": "2026-08-04T09:10:00Z",
      "updated_at": "2026-08-04T09:10:00Z"
    },
    {
      "id": 302,
      "workspace_id": 201,
      "name": "运维 Wiki",
      "description": "",
      "embedding_model": "bge-m3",
      "chunk_size": 800,
      "chunk_overlap": 100,
      "created_at": "2026-08-04T09:12:00Z",
      "updated_at": "2026-08-04T09:12:00Z"
    }
  ]
}
```

---

#### 4.4.3 GET /knowledge-bases/{id}

知识库详情，附带统计信息。

**路径参数：** `id: int`

**响应体 `KnowledgeBaseDetailOut`（200）：**

```python
class KnowledgeBaseDetailOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    description: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    doc_count: int       # 文档总数（不含已删除）
    chunk_count: int     # 分块总数
    created_at: datetime
    updated_at: datetime
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 知识库不存在或当前用户不属于其工作区 |

**curl 示例：**

```bash
curl http://localhost:8000/api/v1/knowledge-bases/301 \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "id": 301,
  "workspace_id": 201,
  "name": "产品手册",
  "description": "产品使用与 FAQ",
  "embedding_model": "bge-m3",
  "chunk_size": 512,
  "chunk_overlap": 64,
  "doc_count": 12,
  "chunk_count": 486,
  "created_at": "2026-08-04T09:10:00Z",
  "updated_at": "2026-08-04T10:22:00Z"
}
```

---

#### 4.4.4 PUT /knowledge-bases/{id}

更新知识库配置。仅 `name`、`description` 可修改；`embedding_model`、`chunk_size`、`chunk_overlap` 创建后不可变（已有向量与分块依赖这些配置），传入即报 400。

**路径参数：** `id: int`

**请求体 `KnowledgeBaseUpdateRequest`：**

```python
class KnowledgeBaseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, max_length=512)
```

> `model_config = ConfigDict(extra="forbid")`：请求体中出现未声明字段（如 `embedding_model`、`chunk_size` 等不可变字段）时直接返回 `400 VALIDATION_ERROR`。

**响应体 `KnowledgeBaseOut`（200）：** 同 4.4.1。

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 传入不可变字段 / 名称非法 |
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 角色为 member |
| 404 | `NOT_FOUND` | 知识库不存在或跨工作区 |
| 409 | `CONFLICT` | 新名称与工作区内其他知识库重复 |

**curl 示例：**

```bash
curl -X PUT http://localhost:8000/api/v1/knowledge-bases/301 \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "产品使用文档与常见问题"}'
```

**响应示例：**

```json
{
  "id": 301,
  "workspace_id": 201,
  "name": "产品手册",
  "description": "产品使用文档与常见问题",
  "embedding_model": "bge-m3",
  "chunk_size": 512,
  "chunk_overlap": 64,
  "created_at": "2026-08-04T09:10:00Z",
  "updated_at": "2026-08-04T11:05:00Z"
}
```

---

#### 4.4.5 DELETE /knowledge-bases/{id}

删除知识库，级联删除其下全部文档、分块与向量，以及该知识库关联的全部会话与消息。仅 `admin` 及以上可操作。

**路径参数：** `id: int`

**响应：`204 No Content`，无响应体。**

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 角色为 member |
| 404 | `NOT_FOUND` | 知识库不存在或跨工作区 |

**curl 示例：**

```bash
curl -X DELETE http://localhost:8000/api/v1/knowledge-bases/301 \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -w "%{http_code}"
# 输出：204
```

---

### 4.5 Documents

#### 4.5.1 POST /knowledge-bases/{kb_id}/documents

上传文档并触发异步解析（Celery 任务）。请求为 `multipart/form-data`。

**路径参数：** `kb_id: int`

**请求表单字段：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 支持 `.md` `.txt` `.pdf` `.docx`，单文件 ≤ 50 MB |

**上传校验要求：**

- 服务端同时校验文件扩展名与 Content-Type（MIME 类型），两者必须匹配支持的类型（`.pdf` → `application/pdf`、`.docx` → `application/vnd.openxmlformats-officedocument.wordprocessingml.document`、`.md` → `text/markdown`、`.txt` → `text/plain`），不匹配返回 `400 VALIDATION_ERROR`
- 落盘前对文件名执行 `secure_filename` 处理（剥离路径分隔符与特殊字符），防止路径穿越

**响应体 `DocumentCreateResponse`（202）：**

```python
class DocumentCreateResponse(BaseModel):
    document_id: int
    status: str  # 固定为 "pending"
```

**文档状态机：**

```
pending → processing → ready
              ↘ failed （可调用 retry 回到 processing）
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 不支持的文件扩展名 / Content-Type 与扩展名不匹配 |
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 角色为 member |
| 404 | `NOT_FOUND` | 知识库不存在或跨工作区 |
| 413 | `FILE_TOO_LARGE` | 文件超过 50 MB |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/knowledge-bases/301/documents \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "file=@./product-manual.pdf"
```

**响应示例：**

```json
{
  "document_id": 401,
  "status": "pending"
}
```

---

#### 4.5.2 GET /knowledge-bases/{kb_id}/documents

列出知识库下的文档，支持分页与状态过滤。

**路径参数：** `kb_id: int`

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数 |
| `status` | string \| null | null | 过滤状态：pending / processing / ready / failed |

**响应体（200）：**

```python
class DocumentSummaryOut(BaseModel):
    id: int
    knowledge_base_id: int
    filename: str
    file_size: int          # 字节
    status: str             # pending | processing | ready | failed
    chunk_count: int
    created_at: datetime

class DocumentListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DocumentSummaryOut]
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | status 取值非法 |
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 知识库不存在或跨工作区 |

**curl 示例：**

```bash
curl "http://localhost:8000/api/v1/knowledge-bases/301/documents?page=1&page_size=20&status=failed" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "total": 1,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": 402,
      "knowledge_base_id": 301,
      "filename": "broken.docx",
      "file_size": 20480,
      "status": "failed",
      "chunk_count": 0,
      "created_at": "2026-08-04T09:40:00Z"
    }
  ]
}
```

---

#### 4.5.3 GET /documents/{id}

文档详情。

**路径参数：** `id: int`

**响应体 `DocumentDetailOut`（200）：**

```python
class DocumentDetailOut(BaseModel):
    id: int
    knowledge_base_id: int
    filename: str
    file_size: int
    status: str              # pending | processing | ready | failed
    chunk_count: int
    error_message: str | None   # 仅 status == "failed" 时非空
    created_at: datetime
    updated_at: datetime
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 文档不存在或跨工作区 |

**curl 示例：**

```bash
curl http://localhost:8000/api/v1/documents/402 \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "id": 402,
  "knowledge_base_id": 301,
  "filename": "broken.docx",
  "file_size": 20480,
  "status": "failed",
  "chunk_count": 0,
  "error_message": "docx 解析失败：文件结构损坏 (BadZipFile)",
  "created_at": "2026-08-04T09:40:00Z",
  "updated_at": "2026-08-04T09:40:12Z"
}
```

---

#### 4.5.4 GET /documents/{id}/chunks

分页查看文档的分块内容。

**路径参数：** `id: int`

**查询参数：** `page`、`page_size`

**响应体（200）：**

```python
class ChunkOut(BaseModel):
    id: int
    document_id: int
    content: str
    token_count: int
    position: int          # 在文档中的序号，从 0 开始
    created_at: datetime

class ChunkListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ChunkOut]
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 文档不存在或跨工作区 |

**curl 示例：**

```bash
curl "http://localhost:8000/api/v1/documents/401/chunks?page=1&page_size=20" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "total": 47,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": 5001,
      "document_id": 401,
      "content": "第一章 产品概述\n本产品是一款面向企业的知识库管理系统……",
      "token_count": 312,
      "position": 0,
      "created_at": "2026-08-04T09:35:02Z"
    }
  ]
}
```

---

#### 4.5.5 DELETE /documents/{id}

删除文档及其全部分块与向量。

**路径参数：** `id: int`

**响应：`204 No Content`，无响应体。**

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 角色为 member |
| 404 | `NOT_FOUND` | 文档不存在或跨工作区 |
| 409 | `CONFLICT` | 文档正在解析中（status == "processing"），需等待完成后删除 |

**curl 示例：**

```bash
curl -X DELETE http://localhost:8000/api/v1/documents/401 \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -w "%{http_code}"
# 输出：204
```

---

#### 4.5.6 POST /documents/{id}/retry

对解析失败（`failed`）的文档重新触发解析任务。

**路径参数：** `id: int`

**请求：无请求体。**

**响应体（202）：**

```python
class DocumentRetryResponse(BaseModel):
    document_id: int
    status: str  # 固定为 "processing"
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 角色为 member |
| 404 | `NOT_FOUND` | 文档不存在或跨工作区 |
| 409 | `CONFLICT` | 文档当前状态不是 failed（如 ready / processing） |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/documents/402/retry \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "document_id": 402,
  "status": "processing"
}
```

---

### 4.6 Chat

#### 4.6.1 POST /chat

对知识库提问。`stream: true` 时返回 SSE 流（见第 5 节）；`stream: false` 时返回一次性 JSON。

**请求体 `ChatRequest`：**

```python
class ChatRequest(BaseModel):
    knowledge_base_id: int
    conversation_id: int | None = None   # 不传则服务端自动创建会话
    message: str = Field(..., min_length=1, max_length=4000)
    stream: bool = True
```

**非流式响应体 `ChatResponse`（200，仅 stream=false）：**

```python
class RetrievalSourceOut(BaseModel):
    chunk_id: int
    document_id: int
    filename: str
    content: str
    score: float          # 相似度得分，0~1

class ChatResponse(BaseModel):
    message_id: int
    conversation_id: int
    answer: str
    sources: list[RetrievalSourceOut]
    token_count: int
```

**流式响应（stream=true）：** `Content-Type: text/event-stream`，事件格式见第 5 节。

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | message 为空或超长 |
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 知识库 / 会话不存在或跨工作区 |
| 429 | `RATE_LIMITED` | 超出 chat 限流（每用户每分钟 20 次） |
| 429 | `QUOTA_EXCEEDED` | 工作区本月 token 配额已用完 |

**curl 示例（流式）：**

```bash
curl -N -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "knowledge_base_id": 301,
    "conversation_id": 601,
    "message": "如何重置管理员密码？",
    "stream": true
  }'
```

**流式响应示例：**

```
data: {"type": "sources", "sources": [{"chunk_id": 5023, "document_id": 401, "filename": "product-manual.pdf", "content": "管理员密码重置：进入设置 → 安全 → 重置密码……", "score": 0.91}]}

data: {"type": "token", "content": "您"}

data: {"type": "token", "content": "可以"}

data: {"type": "token", "content": "在设置页重置密码。"}

data: {"type": "done", "message_id": 7012, "conversation_id": 601, "token_count": 45}
```

**curl 示例（非流式）：**

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"knowledge_base_id": 301, "message": "支持哪些文件格式？", "stream": false}'
```

**非流式响应示例：**

```json
{
  "message_id": 7013,
  "conversation_id": 602,
  "answer": "平台支持 md、txt、pdf、docx 四种格式，单文件不超过 50 MB。",
  "sources": [
    {"chunk_id": 5010, "document_id": 401, "filename": "product-manual.pdf", "content": "支持的文件格式：.md / .txt / .pdf / .docx……", "score": 0.88}
  ],
  "token_count": 62
}
```

---

#### 4.6.2 POST /conversations

创建会话。

**请求体 `ConversationCreateRequest`：**

```python
class ConversationCreateRequest(BaseModel):
    knowledge_base_id: int
    title: str | None = Field(None, max_length=128)  # 不传则默认 "新会话"
```

**响应体 `ConversationOut`（201）：**

```python
class ConversationOut(BaseModel):
    id: int
    knowledge_base_id: int
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 缺少 knowledge_base_id |
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 知识库不存在或跨工作区 |

**curl 示例：**

```bash
curl -X POST http://localhost:8000/api/v1/conversations \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"knowledge_base_id": 301, "title": "密码相关问题"}'
```

**响应示例：**

```json
{
  "id": 601,
  "knowledge_base_id": 301,
  "user_id": 1001,
  "title": "密码相关问题",
  "created_at": "2026-08-04T10:00:00Z",
  "updated_at": "2026-08-04T10:00:00Z"
}
```

---

#### 4.6.3 GET /conversations

列出当前用户的会话，按知识库过滤。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base_id` | int | 是 | 只返回该知识库下的会话 |
| `page` | int | 否 | 默认 1 |
| `page_size` | int | 否 | 默认 20 |

**响应体（200）：**

```python
class ConversationListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ConversationOut]   # 按 updated_at 倒序
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 缺少 knowledge_base_id |
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 知识库不存在或跨工作区 |

**curl 示例：**

```bash
curl "http://localhost:8000/api/v1/conversations?knowledge_base_id=301&page=1&page_size=20" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "total": 2,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": 601,
      "knowledge_base_id": 301,
      "user_id": 1001,
      "title": "密码相关问题",
      "created_at": "2026-08-04T10:00:00Z",
      "updated_at": "2026-08-04T10:05:30Z"
    },
    {
      "id": 602,
      "knowledge_base_id": 301,
      "user_id": 1001,
      "title": "新会话",
      "created_at": "2026-08-04T09:50:00Z",
      "updated_at": "2026-08-04T09:51:10Z"
    }
  ]
}
```

---

#### 4.6.4 GET /conversations/{id}/messages

会话消息历史，按时间正序。仅会话所有者可访问。

**路径参数：** `id: int`

**查询参数：** `page`、`page_size`

**响应体（200）：**

```python
class MessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str              # "user" | "assistant"
    content: str
    token_count: int
    sources: list[RetrievalSourceOut]   # role == "user" 时为空数组
    created_at: datetime

class MessageListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[MessageOut]
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 会话不存在或非本人会话 |

**curl 示例：**

```bash
curl "http://localhost:8000/api/v1/conversations/601/messages?page=1&page_size=20" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "total": 2,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": 7011,
      "conversation_id": 601,
      "role": "user",
      "content": "如何重置管理员密码？",
      "token_count": 12,
      "sources": [],
      "created_at": "2026-08-04T10:05:00Z"
    },
    {
      "id": 7012,
      "conversation_id": 601,
      "role": "assistant",
      "content": "您可以在设置页重置密码。",
      "token_count": 45,
      "sources": [
        {"chunk_id": 5023, "document_id": 401, "filename": "product-manual.pdf", "content": "管理员密码重置：进入设置 → 安全 → 重置密码……", "score": 0.91}
      ],
      "created_at": "2026-08-04T10:05:03Z"
    }
  ]
}
```

---

#### 4.6.5 DELETE /conversations/{id}

删除会话及其全部消息。仅会话所有者可操作。

**路径参数：** `id: int`

**响应：`204 No Content`，无响应体。**

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 401 | `UNAUTHORIZED` | token 无效 |
| 404 | `NOT_FOUND` | 会话不存在或非本人会话 |

**curl 示例：**

```bash
curl -X DELETE http://localhost:8000/api/v1/conversations/601 \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -w "%{http_code}"
# 输出：204
```

---

### 4.7 Admin

#### 4.7.1 GET /admin/usage

按日期区间统计全平台 token 用量。仅平台级管理员（`users.is_superuser == true`）可访问。

> 注：`is_superuser` 为 `users` 表中的布尔字段。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `start_date` | date | 是 | 起始日期（含），YYYY-MM-DD |
| `end_date` | date | 是 | 结束日期（含），YYYY-MM-DD，区间最长 90 天 |

**响应体 `UsageResponse`（200）：**

```python
class DailyUsageOut(BaseModel):
    date: date
    request_count: int     # 当日 chat 请求数
    token_count: int       # 当日消耗 token 总数
    active_users: int      # 当日发起提问的去重用户数

class UsageResponse(BaseModel):
    start_date: date
    end_date: date
    total_requests: int
    total_tokens: int
    daily: list[DailyUsageOut]
```

**错误响应：**

| Status | Code | 场景 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 日期格式错误 / end < start / 区间超 90 天 |
| 401 | `UNAUTHORIZED` | token 无效 |
| 403 | `FORBIDDEN` | 非平台管理员 |

**curl 示例：**

```bash
curl "http://localhost:8000/api/v1/admin/usage?start_date=2026-08-01&end_date=2026-08-04" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**响应示例：**

```json
{
  "start_date": "2026-08-01",
  "end_date": "2026-08-04",
  "total_requests": 320,
  "total_tokens": 152340,
  "daily": [
    {"date": "2026-08-01", "request_count": 80, "token_count": 38200, "active_users": 6},
    {"date": "2026-08-02", "request_count": 45, "token_count": 21040, "active_users": 4},
    {"date": "2026-08-03", "request_count": 95, "token_count": 45600, "active_users": 8},
    {"date": "2026-08-04", "request_count": 100, "token_count": 47500, "active_users": 9}
  ]
}
```

---

#### 4.7.2 GET /admin/health

健康检查，无需认证（供负载均衡 / k8s 探针使用）。

**响应体 `HealthResponse`（200；任一依赖异常时返回 503，结构相同）：**

```python
class HealthResponse(BaseModel):
    status: str      # "ok" | "degraded"
    db: str          # "up" | "down"
    redis: str       # "up" | "down"
    celery: str      # "up" | "down"
```

**curl 示例：**

```bash
curl http://localhost:8000/api/v1/admin/health
```

**响应示例：**

```json
{
  "status": "ok",
  "db": "up",
  "redis": "up",
  "celery": "up"
}
```

---

#### 4.7.3 GET /admin/metrics

Prometheus 格式指标，无需认证（生产环境应通过网络策略仅对内网暴露）。

**响应：** `Content-Type: text/plain; version=0.0.4`

**curl 示例：**

```bash
curl http://localhost:8000/api/v1/admin/metrics
```

**响应示例：**

```
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="POST",endpoint="/chat",status="200"} 1024
# HELP chat_tokens_total Total tokens consumed by chat
# TYPE chat_tokens_total counter
chat_tokens_total 152340
# HELP document_parse_tasks_inflight Documents currently being parsed
# TYPE document_parse_tasks_inflight gauge
document_parse_tasks_inflight 2
# HELP http_request_duration_seconds HTTP request latency
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{le="0.1"} 890
http_request_duration_seconds_bucket{le="1.0"} 1002
http_request_duration_seconds_bucket{le="+Inf"} 1024
```

---

## 5. SSE 流式响应格式

`POST /chat`（`stream: true`）返回 `text/event-stream`。每条事件以 `data: ` 开头，事件之间以空行分隔。

### 5.1 事件类型

| type | 载荷字段 | 说明 |
|------|----------|------|
| `token` | `content: str` | 增量文本片段，按生成顺序推送 |
| `sources` | `sources: [{chunk_id, document_id, filename, content, score}]` | 检索来源，检索完成后推送一次，先于 token |
| `done` | `message_id: int`, `conversation_id: int`, `token_count: int` | 流结束标志，必须是最后一条事件；服务端自动创建会话时客户端由此获知会话 ID |
| `error` | `code: str`, `message: str` | 流中断错误，出现后连接关闭 |

### 5.2 事件序列约定

```
sources（1 次） → token（N 次） → done（1 次）
```

- `sources` 在第一个 `token` 之前推送，前端可先渲染引用来源
- `done` 携带 `conversation_id`：请求未传 `conversation_id` 时服务端自动创建会话，客户端以该事件返回的 ID 为准
- `done` 之后服务端关闭连接，客户端不应再读取
- 任何时刻出错则推送 `error` 事件并关闭连接（HTTP 状态码仍为 200，错误通过事件传达）

### 5.3 完整示例

```
data: {"type": "sources", "sources": [{"chunk_id": 5023, "document_id": 401, "filename": "product-manual.pdf", "content": "管理员密码重置：进入设置 → 安全 → 重置密码……", "score": 0.91}]}

data: {"type": "token", "content": "您"}

data: {"type": "token", "content": "好"}

data: {"type": "token", "content": "，"}

data: {"type": "token", "content": "重置密码的步骤如下……"}

data: {"type": "done", "message_id": 7012, "conversation_id": 601, "token_count": 45}
```

### 5.4 错误事件示例

```
data: {"type": "sources", "sources": []}

data: {"type": "token", "content": "正在"}

data: {"type": "error", "code": "INTERNAL_ERROR", "message": "LLM 服务超时，请重试"}
```

### 5.5 前端消费示例（fetch + ReadableStream）

```typescript
const resp = await fetch("/api/v1/chat", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ knowledge_base_id: 301, message: q, stream: true }),
});

const reader = resp.body!.getReader();
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });

  const lines = buffer.split("\n");
  buffer = lines.pop()!; // 保留不完整的最后一行

  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const event = JSON.parse(line.slice(6));
    switch (event.type) {
      case "token":   appendToAnswer(event.content); break;
      case "sources": renderSources(event.sources);  break;
      case "done":    recordMessageId(event.message_id, event.conversation_id); break;
      case "error":   showError(event.message); break;
    }
  }
}
```

---

## 6. 认证流程时序图

```
 客户端                        API 服务                        Redis/DB
   │                              │                              │
   │ ① POST /auth/register        │                              │
   │ {email, password, nickname}  │                              │
   │─────────────────────────────>│                              │
   │                              │ 密码 bcrypt 哈希后落库        │
   │                              │─────────────────────────────>│
   │                              │<─────────────────────────────│
   │ 201 {user_id}                │                              │
   │<─────────────────────────────│                              │
   │                              │                              │
   │ ② POST /auth/login           │                              │
   │ {email, password}            │                              │
   │─────────────────────────────>│                              │
   │                              │ 校验密码；签发 JWT(30min)     │
   │                              │ 生成 refresh_token 并存 Redis │
   │                              │─────────────────────────────>│
   │                              │<─────────────────────────────│
   │ 200 {access_token,           │                              │
   │      refresh_token}          │                              │
   │<─────────────────────────────│                              │
   │                              │                              │
   │ ③ 业务请求（携带 access_token）│                              │
   │ GET /users/me                │                              │
   │ Authorization: Bearer <JWT>  │                              │
   │─────────────────────────────>│                              │
   │                              │ 验证 JWT 签名与 exp           │
   │ 200 {id, email, ...}         │                              │
   │<─────────────────────────────│                              │
   │                              │                              │
   │ ④ 30 分钟后，JWT 过期         │                              │
   │ GET /workspaces              │                              │
   │─────────────────────────────>│                              │
   │ 401 TOKEN_EXPIRED            │                              │
   │<─────────────────────────────│                              │
   │                              │                              │
   │ ⑤ POST /auth/refresh         │                              │
   │ {refresh_token}              │                              │
   │─────────────────────────────>│                              │
   │                              │ 校验 Redis 中 refresh_token   │
   │                              │─────────────────────────────>│
   │                              │<─────────────────────────────│
   │ 200 {access_token}           │ 签发新 JWT                   │
   │<─────────────────────────────│                              │
   │                              │                              │
   │ ⑥ 用新 token 重放失败的请求    │                              │
   │ GET /workspaces              │                              │
   │─────────────────────────────>│                              │
   │ 200 {items: [...]}           │                              │
   │<─────────────────────────────│                              │
   │                              │                              │
   │ ⑦ POST /auth/logout          │                              │
   │ {refresh_token}              │                              │
   │─────────────────────────────>│                              │
   │                              │ 从 Redis 删除 refresh_token   │
   │                              │─────────────────────────────>│
   │                              │<─────────────────────────────│
   │ 204 No Content               │                              │
   │<─────────────────────────────│                              │
   │                              │                              │
   │ （access_token 仍在有效期内可用，│                              │
   │   自然过期后无法再续签）         │                              │
```

要点：

1. `access_token` 无状态（JWT），服务端不存储，靠签名 + exp 校验
2. `refresh_token` 有状态，存 Redis（TTL 7 天），注销即删除，可主动吊销
3. 客户端收到 `401 TOKEN_EXPIRED` 时应先尝试 refresh 再重放原请求，避免直接跳转登录页
4. refresh_token 不轮换：在注销或 7 天过期前可重复使用，logout 后立即失效

---

## 7. 多租户权限矩阵

### 7.1 角色定义

| 角色 | 作用域 | 说明 |
|------|--------|------|
| `owner` | 工作区 | 工作区创建者，唯一，可删除工作区 |
| `admin` | 工作区 | 可管理成员、知识库与文档，不可删除工作区 |
| `member` | 工作区 | 只读知识库/文档，可提问与管理自己的会话 |
| `superuser` | 平台 | 平台管理员，访问 /admin/usage |

权限检查顺序：**工作区成员资格 → 工作区角色 → 资源归属**。非成员访问任何工作区内资源一律返回 `404 NOT_FOUND`。

### 7.2 端点权限表

图例：✅ 允许　❌ 禁止（403）　— 不适用（资源不属于工作区角色体系）

| 端点 | owner | admin | member | 备注 |
|------|:-----:|:-----:|:------:|------|
| POST /auth/register | — | — | — | 公开 |
| POST /auth/login | — | — | — | 公开 |
| POST /auth/refresh | — | — | — | 公开 |
| POST /auth/logout | ✅ | ✅ | ✅ | 任何已登录用户 |
| GET /users/me | ✅ | ✅ | ✅ | 任何已登录用户 |
| PUT /users/me | ✅ | ✅ | ✅ | 任何已登录用户 |
| POST /workspaces | ✅ | ✅ | ✅ | 任何已登录用户，创建者成为新工作区 owner |
| GET /workspaces | ✅ | ✅ | ✅ | 仅返回本人所在工作区 |
| GET /workspaces/{id} | ✅ | ✅ | ✅ | 需为该工作区成员 |
| DELETE /workspaces/{id} | ✅ | ❌ | ❌ | 仅 owner |
| POST /workspaces/{ws_id}/members | ✅ | ✅ | ❌ | admin 及以上可邀请 |
| PATCH /workspaces/{ws_id}/members/{user_id} | ✅ | ✅ | ❌ | 不可修改 owner 的角色 |
| DELETE /workspaces/{ws_id}/members/{user_id} | ✅ | ✅ | ❌ | 不可移除 owner |
| GET /workspaces/{ws_id}/usage | ✅ | ✅ | ✅ | 成员均可查看本空间配额 |
| POST /workspaces/{ws_id}/knowledge-bases | ✅ | ✅ | ❌ | |
| GET /workspaces/{ws_id}/knowledge-bases | ✅ | ✅ | ✅ | |
| GET /knowledge-bases/{id} | ✅ | ✅ | ✅ | 需属于其工作区 |
| PUT /knowledge-bases/{id} | ✅ | ✅ | ❌ | |
| DELETE /knowledge-bases/{id} | ✅ | ✅ | ❌ | 级联删除文档+分块+会话+消息 |
| POST /knowledge-bases/{kb_id}/documents | ✅ | ✅ | ❌ | |
| GET /knowledge-bases/{kb_id}/documents | ✅ | ✅ | ✅ | |
| GET /documents/{id} | ✅ | ✅ | ✅ | |
| GET /documents/{id}/chunks | ✅ | ✅ | ✅ | |
| DELETE /documents/{id} | ✅ | ✅ | ❌ | |
| POST /documents/{id}/retry | ✅ | ✅ | ❌ | |
| POST /chat | ✅ | ✅ | ✅ | member 的核心使用场景 |
| POST /conversations | ✅ | ✅ | ✅ | |
| GET /conversations | ✅ | ✅ | ✅ | 仅返回本人会话 |
| GET /conversations/{id}/messages | ✅ | ✅ | ✅ | 仅会话所有者 |
| DELETE /conversations/{id} | ✅ | ✅ | ✅ | 仅会话所有者 |
| GET /admin/usage | ❌ | ❌ | ❌ | 仅 superuser |
| GET /admin/health | — | — | — | 公开（探针） |
| GET /admin/metrics | — | — | — | 公开（仅内网暴露） |

### 7.3 关键规则说明

1. **会话私有**：会话（conversation）绑定 `user_id`，即使同为工作区成员也互相不可见；owner/admin 不能查看他人的会话与消息。
2. **知识库共享**：知识库对工作区全体成员可见、可提问，但写操作（创建/修改/删除/上传文档）需 admin 及以上。
3. **跨租户隔离**：所有按 ID 访问的资源端点，服务端先查资源所属工作区，再校验当前用户的成员资格；校验失败统一返回 `404 NOT_FOUND`，不暴露资源是否存在。
4. **superuser 与工作区角色正交**：superuser 是平台级身份，不自动拥有任何工作区的 owner 权限（除 `/admin/usage` 外不绕过工作区权限检查）。
