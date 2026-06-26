# T-024: 会话创建/查询/删除

## 基本信息
- 对应 Spec: specs/conversation-memory/01-requirements.md REQ-001, REQ-002, REQ-010, REQ-011
- 对应 AC: AC-001~AC-005, AC-011~AC-013
- 依赖: T-007, Redis 基础设施
- 预计工时: 1.5 天

## 输入
- `specs/conversation-memory/01-requirements.md` — 会话管理需求
- `specs/conversation-memory/02-data-model.md` — 会话数据模型
- `specs/conversation-memory/03-api-contract.md` — 会话 API 契约
- `src/common/crypto.py` — 加密工具（T-007 产出）

## 输出
- `src/conversation_memory/session_manager.py` — 会话管理模块
- `src/conversation_memory/session_repository.py` — 会话数据仓库
- `src/conversation_memory/redis_session_cache.py` — Redis 会话状态缓存层（TTL 滑动窗口）
- `tests/conversation_memory/test_session_manager.py` — 会话管理测试

## 实现要求
1. 会话创建：生成 `session_id`（UUID），初始化空的 Slot 和消息历史，设置 TTL（默认 30min）
2. 会话查询：支持按 `session_id` 查询会话详情，包含 Slot 状态、消息历史、创建时间
3. 会话删除：支持主动删除和 TTL 过期自动清理
4. 会话列表：支持按用户维度查询活跃会话列表（分页）
5. 消息追加：每轮对话追加到消息历史，消息包含 `role`（user/assistant/system）、`content`、`timestamp`
6. 会话状态机：`active` → `expired` / `deleted`，状态转换不可逆
7. 会话数据加密存储：会话消息中的 PII 字段使用 T-007 加密
8. 关键设计决策：会话 TTL 使用 Redis EXPIRE 滑动窗口管理（1800s），MongoDB TTL Index 作为兜底硬过期（86400s）
   - 创建会话时：Redis SET conversation:{id}:state + EXPIRE 1800
   - 每次交互时：Redis EXPIRE conversation:{id}:state 1800（滑动窗口重置）
   - 读取状态：优先 Redis GET → 未命中则 MongoDB 读取 → 回写 Redis
   - 竞态防护：每轮对话结束追加消息时，必须同步更新 MongoDB 的 last_active_at 字段（防止 MongoDB TTL 在 Redis 滑动窗口期间硬删记录）
9. 禁止事项：禁止在会话中存储完整简历数据（只存引用 ID）；禁止忽略 TTL 过期的会话清理（Redis 自动过期 + MongoDB TTL Index 双层保障）

## 验收检查点

### 前置确认
- [ ] T-007（加密工具）已完成
- [ ] 容器环境已启动
- [ ] MongoDB TTL Index 已配置
- [ ] 数据库 Migration 已执行

### AC 验收
- [ ] AC-001: 创建会话返回 `session_id`，会话状态为 `active`
- [ ] AC-002: 查询会话返回完整信息（Slot、消息历史、状态）
- [ ] AC-003: 删除会话后状态变为 `deleted`，不可再查询
- [ ] AC-004: TTL 过期后会话自动清理（Redis 过期 + MongoDB TTL 双层）
- [ ] AC-014: 每次交互后 Redis EXPIRE 正确重置（滑动窗口验证）
- [ ] AC-015: Redis 不可用时降级到 MongoDB 直读（不中断服务）
- [ ] AC-012: 消息追加成功，消息历史按时间排序
- [ ] AC-013: 会话列表查询支持分页，返回 `session_id`、`created_at`、`last_active_at`

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] TTL 可配置
- [ ] MongoDB 操作有异常处理（连接失败、超时、写入冲突）
- [ ] PII 字段加密正确
- [ ] 类型标注完整


- [ ] AC-005: 每轮对话后 ConversationState 正确更新（last_query, last_filters, last_candidates, turn_count）
- [ ] AC-011: 会话数据持久化到 MongoDB 后，服务重启可恢复完整状态（Slot + 消息历史）

### Spec 一致性
- [ ] 会话数据模型与 `specs/conversation-memory/02-data-model.md` 一致
- [ ] API 接口与 `03-api-contract.md` 一致
- [ ] 状态机转换与 REQ-010 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
