# T-033: 对话管理 API + Audit Log 中间件

## 基本信息
- **对应 Spec**: api-layer REQ-003, REQ-004, REQ-005, REQ-009
- **对应 AC**: AC-005, AC-006
- **依赖任务**: T-024（对话状态管理）, T-005（Audit Log 中间件基础）
- **预计工时**: 1.5 天
- **优先级**: P1

## 输入
- T-024 产出的对话状态管理模块（conversation CRUD、状态机）
- T-005 产出的 Audit Log 中间件基础
- API Layer Spec `03-api-contract.md` 中 REQ-003~005, REQ-009 的定义

## 输出
- `src/api/v1/conversations.py` — 对话管理路由
- `src/api/v1/schemas/conversation.py` — Pydantic 模型
- `src/api/middleware/audit.py` — Audit Log 中间件
- 单元测试 `tests/api/test_conversations.py`
- 单元测试 `tests/middleware/test_audit.py`

## 实现要求

### 对话管理端点
```
GET    /api/v1/conversations              # 列出当前用户的对话列表
POST   /api/v1/conversations              # 创建新对话
GET    /api/v1/conversations/{id}         # 获取对话详情（含消息历史）
PUT    /api/v1/conversations/{id}         # 更新对话标题/元信息
DELETE /api/v1/conversations/{id}         # 删除对话（软删除）
GET    /api/v1/conversations/{id}/messages # 分页获取消息历史
```

### 对话状态
1. 每个对话有状态字段：`active` / `archived` / `deleted`
2. 创建时默认 `active`
3. 删除为软删除，标记为 `deleted`，30 天后物理清理

### Audit Log 中间件
1. 记录所有 API 请求的审计日志
2. 字段：`timestamp`, `user_id`, `method`, `path`, `status_code`, `latency_ms`, `ip`
3. 写入 MongoDB `audit_logs` collection
4. 异步写入，不阻塞请求
5. 敏感操作（login, upload, delete）标记 `action_type`

### 错误处理
- 401: 未认证
- 403: 访问他人对话
- 404: 对话不存在
- 422: 参数校验失败

## 验收检查点

### 前置确认
- [ ] T-024 已完成并通过验收（对话状态管理可用）
- [ ] T-005 已完成并通过验收（Audit Log 基础可用）
- [ ] JWT 认证中间件已就绪（T-032 产出）

### AC 验收
- [ ] **AC-005**: 用户可创建对话、查看对话列表、获取对话详情及消息历史
- [ ] **AC-006**: 所有 API 请求被 Audit Log 记录，含 user_id、method、path、status_code、latency

### 代码质量
- [ ] 对话列表支持分页（`skip` / `limit` 参数）
- [ ] 消息历史支持分页，按时间正序返回
- [ ] Audit Log 异步写入，不增加请求延迟超过 5ms
- [ ] 软删除不影响正常查询（默认只查 `active` 状态）
- [ ] 单元测试覆盖率 ≥ 80%
- [ ] `ruff check` / `mypy` 无报错

### Spec 一致性
- [ ] 所有端点的请求/响应字段与 Spec 完全一致
- [ ] Audit Log 字段与 REQ-009 定义一致
- [ ] 对话状态机转换符合 Spec 业务规则

### 通过判定
- [ ] 所有 AC 验收项通过
- [ ] curl 测试 CRUD 全流程通过
- [ ] Audit Log collection 中有对应记录
