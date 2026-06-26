# T-025: Slot 合并（增量/覆盖/重置）

## 基本信息
- 对应 Spec: specs/conversation-memory/01-requirements.md REQ-004~REQ-007
- 对应 AC: AC-006~AC-009
- 依赖: T-024
- 预计工时: 1.5 天

## 输入
- `specs/conversation-memory/01-requirements.md` — Slot 合并需求
- `specs/conversation-memory/02-data-model.md` — Slot 数据模型
- `specs/conversation-memory/04-business-rules.md` — Slot 合并规则
- `src/conversation_memory/session_manager.py` — 会话管理（T-024 产出）

## 输出
- `src/conversation_memory/slot_manager.py` — Slot 合并模块
- `src/conversation_memory/slot_strategies.py` — 合并策略实现
- `tests/conversation_memory/test_slot_manager.py` — Slot 合并测试

## 实现要求
1. 三种合并策略：
   - 增量合并（Incremental）：新 Slot 中有值的字段覆盖旧值，无值的字段保留旧值
   - 覆盖合并（Override）：新 Slot 完全覆盖旧 Slot
   - 重置（Reset）：清空所有 Slot，重新开始
2. 默认使用增量合并，用户明确说"重新搜索"时触发重置，"换成..."时触发覆盖
3. Slot 合并时记录 `merge_log`：`merge_strategy`、`before_snapshot`、`after_snapshot`、`changed_fields`
4. 支持 Slot 历史回溯：保留最近 5 次 Slot 快照，支持"撤销上一步"
5. Slot 类型校验：合并前验证字段类型（如 `experience` 必须是数字范围），校验失败保留旧值 + 警告
6. 并发安全：同一会话的 Slot 合并使用 MongoDB indOneAndUpdate 原子操作，防止并发写入冲突（V1 并发量低，无需分布式锁）
7. 关键设计决策：默认增量合并而非覆盖，因为多轮对话中用户通常是在逐步补充条件
8. 禁止事项：禁止合并策略硬编码（必须通过 Strategy Pattern 实现）；禁止忽略类型校验直接合并

## 验收检查点

### 前置确认
- [ ] T-024（会话 CRUD）已完成
- [ ] 容器环境已启动
- [ ] MongoDB 连接正常

### AC 验收
- [ ] AC-006: 增量合并正确，新字段覆盖旧字段，未提及字段保留
- [ ] AC-007: 覆盖合并正确，旧 Slot 被完全替换
- [ ] AC-008: 重置正确，所有 Slot 清空
- [ ] AC-009: 合并日志完整记录 `before_snapshot` 和 `after_snapshot`

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] Strategy Pattern 实现清晰
- [ ] 并发锁逻辑正确，有超时释放
- [ ] Slot 历史回溯逻辑正确
- [ ] 类型标注完整

### Spec 一致性
- [ ] 合并策略与 REQ-004~REQ-006 一致
- [ ] 合并日志字段与 REQ-007 一致
- [ ] Slot 类型定义与 `02-data-model.md` 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
