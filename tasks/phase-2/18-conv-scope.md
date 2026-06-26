# T-026: 检索范围决策 + 候选人引用

## 基本信息
- 对应 Spec: specs/conversation-memory/01-requirements.md REQ-008, REQ-012
- 对应 AC: AC-010, AC-014, AC-015
- 依赖: T-025, T-014
- 预计工时: 1.5 天

## 输入
- `specs/conversation-memory/01-requirements.md` — 检索范围与候选人引用需求
- `specs/conversation-memory/04-business-rules.md` — 范围决策规则
- `src/conversation_memory/slot_manager.py` — Slot 合并（T-025 产出）
- `src/resume_store/repository.py` — Resume 数据仓库（T-014 产出）

## 输出
- `src/conversation_memory/scope_decider.py` — 检索范围决策模块
- `src/conversation_memory/candidate_ref.py` — 候选人引用模块
- `tests/conversation_memory/test_scope_decider.py` — 范围决策测试
- `tests/conversation_memory/test_candidate_ref.py` — 候选人引用测试

## 实现要求
1. 检索范围决策：根据 Slot 完整度决定检索范围
   - Slot 充分（≥3 个关键字段有值）→ 全量向量检索
   - Slot 不足（1-2 个字段）→ 先请求用户补充，同时用已有字段做粗检索
   - Slot 为空 → 引导用户描述需求，不触发检索
2. 候选人引用管理：用户在对话中提到的候选人（如"张三"、"第2个"）自动关联到 `resume_id`
3. 引用解析规则：
   - 名字匹配 → 在当前检索结果中按姓名查找
   - 序号匹配（"第N个"、"N号"）→ 按检索结果排序取第 N 个
   - 指代词（"这个人"、"他"）→ 引用最近一次提到的候选人
4. 引用冲突处理：同名多人时返回列表让用户选择
5. 引用缓存：当前会话中的引用关系持久化，跨轮次可用
6. 关键设计决策：范围决策是"乐观+引导"策略，不会因为 Slot 不足而完全拒绝检索
7. 禁止事项：禁止在引用解析时忽略同名冲突；禁止跨会话引用候选人

## 验收检查点

### 前置确认
- [ ] T-025（Slot 合并）已完成
- [ ] T-014（Resume Store CRUD）已完成
- [ ] 容器环境已启动

### AC 验收
- [ ] AC-010: Slot 充分时正确触发全量检索；Slot 不足时返回引导性回复 + 粗检索结果
- [ ] AC-014: "第2个" 正确解析为检索结果列表的第 2 条记录的 `resume_id`
- [ ] AC-015: 同名冲突时返回候选列表，不自动选择

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] Slot 充分度判定可配置
- [ ] 引用解析规则可扩展
- [ ] 同名冲突处理逻辑有完整测试
- [ ] 类型标注完整

### Spec 一致性
- [ ] 范围决策规则与 REQ-008 一致
- [ ] 引用解析规则与 REQ-012 一致
- [ ] 引用冲突处理与 `04-business-rules.md` 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
