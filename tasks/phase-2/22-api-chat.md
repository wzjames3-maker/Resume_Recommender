# T-030: FastAPI /api/v1/chat（Streaming SSE）

## 基本信息
- **对应 Spec**: api-layer REQ-001
- **对应 AC**: AC-001, AC-002
- **依赖任务**: T-027（Hybrid Retrieval 核心）, T-006（FastAPI 应用骨架）
- **预计工时**: 1.5 天
- **优先级**: P0

## 输入
- T-027 产出的 `recruitment.search` 模块（含 Intent 识别、Hybrid Retrieval、Filter、Rerank）
- T-006 产出的 FastAPI 应用骨架（含 CORS、异常处理、依赖注入基础）
- API Layer Spec `03-api-contract.md` 中 REQ-001 的请求/响应定义
- JWT 认证中间件（复用 T-032 产出或已有 auth 依赖）

## 输出
- `src/api/v1/chat.py` — 路由文件，含 `/api/v1/chat` 端点
- `src/api/v1/schemas/chat.py` — 请求/响应 Pydantic 模型
- `src/api/deps.py` — JWT 认证依赖注入（`get_current_user`）
- Streaming SSE 响应格式：`data: {"type": "token", "content": "..."}\n\n`
- 单元测试 `tests/api/test_chat.py`

## 实现要求

### SSE Streaming
1. 使用 `StreamingResponse` + `text/event-stream` Content-Type
2. 每个 SSE event 格式：`data: {JSON}\n\n`，支持以下 event type：
   - `token` — LLM 流式输出的 token
   - `sources` — 检索到的候选人摘要列表
   - `done` — 流结束标记
3. 前端通过 `EventSource` 接收

### 端点定义

**注意：本任务是所有对话类 API 路由的统一入口**。T-027/T-028/T-029 产出的 Pipeline 模块在本任务中被路由调用：
- 
ecruitment.search → 通过 /api/v1/chat 路由调用 search_pipeline
- 
ecruitment.refine → 通过 /api/v1/chat 路由调用 
efine_pipeline
- candidate.lookup / candidate.compare → 通过 /api/v1/chat 路由调用 lookup_pipeline / compare_pipeline

前端所有对话交互统一走 /api/v1/chat 端点，后端通过 Intent Router 自动分发到对应 Pipeline。不需要独立的 /api/v1/search、/api/v1/refine、/api/v1/candidate 路由——所有意图在 /api/v1/chat 内部通过 Intent Router 分发。
```
POST /api/v1/chat
Headers: Authorization: Bearer <JWT>
Body: {
  "message": "找一个3年经验的Python开发",
  "conversation_id": "uuid (可选，续对话时传入)",
  "filters": { "location": "上海", "min_exp": 3 } (可选)
}
Response: SSE Stream
```

### 认证
1. 所有请求必须携带有效 JWT
2. 使用 `Depends(get_current_user)` 注入当前用户
3. 无效/过期 token 返回 `401 Unauthorized`

### 错误处理
- 400: 请求参数校验失败
- 401: JWT 无效或过期
- 500: 内部错误时返回 `{"type": "error", "message": "..."}`

## 验收检查点

### 前置确认
- [ ] T-027 已完成并通过验收
- [ ] T-006 已完成并通过验收
- [ ] FastAPI 应用可正常启动
- [ ] JWT 认证中间件可用

### AC 验收
- [ ] **AC-001**: 用户发送搜索请求，收到 SSE 流式响应，token 逐个输出
- [ ] **AC-002**: 流结束后收到 `sources` 事件，包含候选人列表摘要

### 代码质量
- [ ] Pydantic 模型完整定义请求/响应 schema
- [ ] SSE 生成器异常时正确关闭连接并输出 error event
- [ ] 单元测试覆盖率 ≥ 80%（mock LLM + retrieval）
- [ ] `ruff check` / `mypy` 无报错

### Spec 一致性
- [ ] 请求/响应字段与 `03-api-contract.md` REQ-001 完全一致
- [ ] SSE event 格式符合 Spec 定义
- [ ] 认证机制符合 Spec 中安全要求

### 通过判定
- [ ] 所有 AC 验收项通过
- [ ] 所有代码质量检查项通过
- [ ] 手动 curl 测试 SSE 流输出正常
