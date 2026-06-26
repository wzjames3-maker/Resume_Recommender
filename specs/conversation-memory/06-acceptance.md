<!-- Module: conversation-memory -->
<!-- Spec Layer: 06 - Acceptance Criteria -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 验收标准：Conversation Memory（对话记忆模块）

## 验收总览

| ID | 覆盖 | 场景 | 关联 |
|----|------|------|------|
| AC-001 | REQ-001 | 创建 Conversation | P0 |
| AC-002 | REQ-001 | 获取已创建的 Conversation | P0 |
| AC-003 | REQ-002 | 保存 user Message | P0 |
| AC-004 | REQ-002 | 保存 assistant Message | P0 |
| AC-005 | REQ-003 | 维护 ConversationState 更新 | P0 |
| AC-006 | REQ-004 | 增量合并 Slots | P0 |
| AC-007 | REQ-005 | 条件覆盖 Slots | P0 |
| AC-008 | REQ-006 | 排除条件追加不覆盖 | P0 |
| AC-009 | REQ-007 | 新 search 时条件重置 | P0 |
| AC-010 | REQ-008 | 检索范围决策 | P1 |
| AC-011 | REQ-009 | MongoDB 持久化与恢复 | P0 |
| AC-012 | REQ-010 | 对话列表查询 | P1 |
| AC-013 | REQ-011 | 对话软删除 | P2 |
| AC-014 | REQ-012 | 候选人按位置引用 | P0 |
| AC-015 | REQ-012 | 候选人按姓名引用 | P0 |

---

## AC-001: 创建 Conversation

**关联**：REQ-001

### Given
- user_id = "user_001"

### When
- 调用 `create_conversation("user_001")`

### Then
- 返回 Conversation 对象
- conversation_id 为有效 UUID v4 字符串
- user_id = "user_001"
- title 匹配格式 `"对话 {YYYY-MM-DD HH:mm}"`
- turn_count = 0
- status = "active"
- created_at 和 updated_at 为有效时间戳

### 验证方式
```python
conv = await store.create_conversation("user_001")
assert UUID(conv.conversation_id)  # valid UUID
assert conv.user_id == "user_001"
assert conv.title.startswith("对话 ")
assert conv.turn_count == 0
assert conv.status == "active"
assert conv.created_at <= datetime.utcnow()
```

---

## AC-002: 获取已创建的 Conversation

**关联**：REQ-001

### Given
- 已创建 conversation_id = "xxx"

### When
- 调用 `get_conversation("xxx")`

### Then
- 返回 Conversation 对象
- 所有字段与创建时一致

### When（不存在）
- 调用 `get_conversation("nonexistent")`

### Then
- 返回 None

---

## AC-003: 保存 user Message

**关联**：REQ-002

### Given
- 已创建 conversation_id = "xxx"
- role = "user"
- content = "找5年Java工程师"
- intent = "recruitment.search"
- slots = {"job_title": "Java工程师", "experience": 5}

### When
- 调用 `add_message("xxx", "user", "找5年Java工程师", "recruitment.search", slots)`

### Then
- 返回 Message 对象
- message_id 为有效 UUID
- conversation_id = "xxx"
- role = "user"
- content = "找5年Java工程师"
- intent = "recruitment.search"
- slots = {"job_title": "Java工程师", "experience": 5}
- conversation.turn_count 递增 1
- intent_history 追加 "recruitment.search"

---

## AC-004: 保存 assistant Message

**关联**：REQ-002

### Given
- 已创建 conversation_id = "xxx"
- role = "assistant"
- content = "为您找到 10 位候选人..."
- intent = "recruitment.search"

### When
- 调用 `add_message("xxx", "assistant", content, intent, {})`

### Then
- 返回 Message 对象
- role = "assistant"
- conversation.turn_count 递增 1
- intent_history 不追加（仅追加 user 消息的 intent）

---

## AC-005: 维护 ConversationState 更新

**关联**：REQ-003

### Given
- conversation_id = "xxx"，初始 turn_count = 0

### When
- `add_message("xxx", "user", "找5年Java", "recruitment.search", {job_title: "Java", experience: 5})`
- 更新 last_query = {job_title: "Java", experience: 5}
- 更新 last_filters = {job_title: "Java", experience: 5}

### Then
- `get_state("xxx")` 返回：
  - last_query = {job_title: "Java", experience: 5}
  - last_filters = {job_title: "Java", experience: 5}
  - turn_count = 1
  - intent_history = ["recruitment.search"]

---

## AC-006: 增量合并 Slots

**关联**：REQ-004, RULE-002

### Given
- conversation_id = "xxx"
- state.last_filters = {skills: ["Java"], city: "杭州"}
- new_slots = {gender: "女"}

### When
- 调用 `merge_slots("xxx", {gender: "女"})`

### Then
- 返回 SlotMergeResult
- merged_slots = {skills: ["Java"], city: "杭州", gender: "女"}
- merge_type = "增量"
- changed_fields = ["gender"]
- search_scope = "within_candidates_fallback"

### MongoDB 验证
```python
state = await store.get_state("xxx")
assert state.last_filters == {"skills": ["Java"], "city": "杭州", "gender": "女"}
```

---

## AC-007: 条件覆盖 Slots

**关联**：REQ-005, RULE-003

### Given
- state.last_filters = {count: 10, sort_by: "score"}
- new_slots = {count: 20}

### When
- 调用 `merge_slots("xxx", {count: 20})`

### Then
- merged_slots = {count: 20, sort_by: "score"}
- merge_type = "覆盖"
- changed_fields = ["count"]
- search_scope = "within_candidates"

---

## AC-008: 排除条件追加不覆盖

**关联**：REQ-006, RULE-004

### Given
- state.last_filters = {skills: ["Java"], exclude: ["外包"]}
- new_slots = {exclude: ["留学生"]}

### When
- 调用 `merge_slots("xxx", {exclude: ["留学生"]})`

### Then
- merged_slots 中 exclude = ["外包", "留学生"]
- merge_type = "增量"
- changed_fields = ["exclude"]

### Given（去重）
- state.last_filters = {exclude: ["外包"]}
- new_slots = {exclude: ["外包"]}

### When
- 调用 `merge_slots("xxx", {exclude: ["外包"]})`

### Then
- exclude = ["外包"]（不重复）

---

## AC-009: 新 search 时条件重置

**关联**：REQ-007, RULE-001

### Given
- state.last_filters = {skills: ["Java"], city: "杭州", gender: "女", exclude: ["外包"]}
- state.last_candidates = [张三, 李四]
- state.turn_count = 5
- state.intent_history = ["recruitment.search", "recruitment.refine"]

### When
- 调用 `reset_state("xxx")`

### Then
- state.last_query = {}
- state.last_filters = {}
- state.last_candidates = []
- state.last_sort_by = None
- state.turn_count = 5（不清空）
- state.intent_history = ["recruitment.search", "recruitment.refine"]（不清空）

---

## AC-010: 检索范围决策

**关联**：REQ-008, RULE-002~RULE-004

### 场景 A：追加过滤条件
- new_slots = {gender: "女"}（新 key）
- search_scope = "within_candidates_fallback"

### 场景 B：仅修改数量
- new_slots = {count: 20}（Query Slot 覆盖）
- search_scope = "within_candidates"

### 场景 C：修改核心条件
- new_slots = {job_title: "算法工程师"}（核心字段变更）
- search_scope = "full_search"

### 场景 D：排除条件
- new_slots = {exclude: ["外包"]}
- search_scope = "within_candidates"

---

## AC-011: MongoDB 持久化与恢复

**关联**：REQ-009, RULE-009, EC-007

### 场景 A：正常持久化
```
Given: MongoDB 可用
When: create_conversation + add_message + merge_slots
Then: 重启进程后，get_conversation 能查到之前的数据
```

### 场景 B：降级到内存
```
Given: MongoDB 不可用（连接超时）
When: create_conversation("user_001")
Then: 操作成功，返回 Conversation 对象
And: 日志中有 WARNING "MongoDB unavailable, falling back to in-memory"
```

### 场景 C：降级后数据不持久化
```
Given: MongoDB 不可用，已降级到内存
And: 已在内存中创建 conversation
When: 重启进程
Then: get_conversation 返回 None（内存数据丢失）
```

---

## AC-012: 对话列表查询

**关联**：REQ-010

### Given
- user_id = "user_001" 有 3 个 active 对话
- user_id = "user_001" 有 1 个 deleted 对话

### When
- 调用 `list_conversations("user_001")`

### Then
- 返回 3 个 Conversation（不含 deleted）
- 按 updated_at 降序排列

### Given（分页）
- user_id = "user_001" 有 25 个 active 对话

### When
- 调用 `list_conversations("user_001", limit=10, offset=10)`

### Then
- 返回 10 个 Conversation（第 11~20 条）

---

## AC-013: 对话软删除

**关联**：REQ-011

### Given
- conversation_id = "xxx"，status = "active"

### When
- 调用 `delete_conversation("xxx")`

### Then
- 返回 True
- conversation.status = "deleted"
- list_conversations 不返回该对话
- messages 不被物理删除（保留审计记录）

### Given（不存在）
- conversation_id = "nonexistent"

### When
- 调用 `delete_conversation("nonexistent")`

### Then
- 返回 False

---

## AC-014: 候选人按位置引用

**关联**：REQ-012, RULE-006

### Given
- last_candidates = [张三(rank=1), 李四(rank=2), 王五(rank=3)]
- ref = "last_candidates[0]"

### When
- 调用 `resolve_candidate_ref("xxx", "last_candidates[0]")`

### Then
- 返回 CandidateRef(candidate_name="张三", rank=1)

### Given（越界）
- ref = "last_candidates[10]"

### Then
- 返回 None

### Given（空列表）
- last_candidates = []

### Then
- 返回 None

---

## AC-015: 候选人按姓名引用

**关联**：REQ-012, RULE-006, RULE-007

### 场景 A：精确匹配 1 人
```
Given: last_candidates = [张三, 李四, 王五]
When: resolve_candidate_ref("xxx", "张三")
Then: 返回 CandidateRef(candidate_name="张三")
```

### 场景 B：精确匹配多人
```
Given: last_candidates = [张三, 张四, 李四]
When: resolve_candidate_ref("xxx", "张")
Then: 返回 List[CandidateRef] = [张三, 张四]（模糊匹配）
```

### 场景 C：匹配 0 人
```
Given: last_candidates = [张三, 李四]
When: resolve_candidate_ref("xxx", "王五")
Then: 返回 None
```

---

## 验收矩阵（覆盖追溯）

| 需求 | AC 编号 | 业务规则 | 边界情况 |
|------|---------|----------|----------|
| REQ-001 | AC-001, AC-002 | - | EC-002 |
| REQ-002 | AC-003, AC-004 | - | EC-004 |
| REQ-003 | AC-005 | RULE-005 | EC-004 |
| REQ-004 | AC-006 | RULE-002 | EC-005 |
| REQ-005 | AC-007 | RULE-003 | EC-005 |
| REQ-006 | AC-008 | RULE-004 | - |
| REQ-007 | AC-009 | RULE-001 | - |
| REQ-008 | AC-010 | RULE-002~004 | - |
| REQ-009 | AC-011 | RULE-009 | EC-007 |
| REQ-010 | AC-012 | - | - |
| REQ-011 | AC-013 | - | - |
| REQ-012 | AC-014, AC-015 | RULE-006, RULE-007 | EC-003 |
