<!-- Module: conversation-memory -->
<!-- Spec Layer: 01 - Requirements -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 功能需求：Conversation Memory（对话记忆模块）

## 需求总览

| ID | 需求 | 优先级 | 关联 PRD / 规则 |
|----|------|--------|----------------|
| REQ-001 | 创建 / 获取 Conversation | P0 | FR-007 |
| REQ-002 | 保存每轮 Message | P0 | FR-007 |
| REQ-003 | 维护 Conversation State | P0 | FR-006, FR-007 |
| REQ-004 | 增量合并 Slots | P0 | FR-006, BR-05 |
| REQ-005 | 条件覆盖 Slots | P0 | FR-006, BR-05 |
| REQ-006 | 排除条件处理 | P0 | FR-006, BR-05 |
| REQ-007 | 条件重置 | P0 | FR-006, BR-07 |
| REQ-008 | 检索范围决策 | P1 | BR-06 |
| REQ-009 | 对话历史持久化 | P0 | FR-007, BR-09 |
| REQ-010 | 对话列表查询 | P1 | FR-007 |
| REQ-011 | 对话删除 | P2 | - |
| REQ-012 | last_candidates 引用 | P0 | FR-006, BR-14 |

---

## REQ-001: 创建 / 获取 Conversation

**描述**：系统必须能够创建新的 Conversation 会话，并通过 conversation_id 获取已有会话。

**输入**：
- `user_id: str` — 用户标识（JWT 中的 user_id）

**输出**：
- `Conversation` 对象（含 conversation_id, user_id, title, turn_count, status, created_at, updated_at）

**规则**：
- conversation_id 使用 UUID v4 生成
- title 自动生成："对话 {YYYY-MM-DD HH:mm}"
- 新建时 turn_count = 0, status = "active"
- get_conversation 时如果 conversation_id 不存在，返回 None（上层决定是否 404）

**关联**：PRD FR-007, 04-domain-model.md Conversation 实体

---

## REQ-002: 保存每轮 Message

**描述**：系统必须在每轮交互后保存 user 和 assistant 的 Message。

**输入**：
- `conversation_id: str` — 会话 ID
- `role: str` — "user" 或 "assistant"
- `content: str` — 消息文本
- `intent: str` — 识别的意图（user 消息为识别结果，assistant 消息为触发的 workflow）
- `slots: dict` — 提取的 Slots（快照）

**输出**：
- `Message` 对象（含 message_id, conversation_id, role, content, intent, slots, created_at）

**规则**：
- message_id 使用 UUID v4 生成
- 每次 add_message 同时递增 conversation.turn_count
- assistant 消息的 intent 继承触发它的 user 消息的 intent
- slots 为该轮提取的原始 Slots，不做合并（合并结果在 ConversationState 中）

**关联**：PRD FR-007, 04-domain-model.md Message 实体

---

## REQ-003: 维护 Conversation State

**描述**：系统必须在每轮交互后更新 ConversationState，维护最新的查询上下文。

**状态字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| last_query | dict | 上一次查询的完整 Slots |
| last_filters | dict | 上一次生效的过滤条件 |
| last_candidates | list[dict] | 上一次推荐的候选人列表（含 candidate_id, candidate_name, rank, score） |
| last_sort_by | str | 上一次排序方式 |
| turn_count | int | 当前对话轮次 |
| intent_history | list[str] | 历史意图序列 |

**规则**：
- ConversationState 与 Conversation 持久化在同一个 MongoDB document 中（嵌入式）
- 每次 add_message 后根据 intent 和 slots 更新 state
- `recruitment.search` → 调用 reset_state 后更新全部字段
- `recruitment.refine` → 调用 merge_slots 后更新 last_filters 和 last_query
- 推荐完成后更新 last_candidates 和 last_sort_by
- intent_history 追加本轮 intent（只追加 user 消息的 intent）

**关联**：PRD FR-006, FR-007, 03-slot-definition.md Conversation Slot

---

## REQ-004: 增量合并 Slots

**描述**：当 intent 为 `recruitment.refine` 时，新条件追加到已有 last_filters 中。

**规则**：
- 新 Slot 与已有 Slot 不存在同类 → 直接追加
- 示例：`已有 {skills: ["Java"], city: "杭州"}` + `新增 {gender: "女"}` → `{skills: ["Java"], city: "杭州", gender: "女"}`
- 合并后返回 `SlotMergeResult`（merged_slots, merge_type="增量", changed_fields）

**关联**：PRD FR-006, 05-business-rules.md BR-05

---

## REQ-005: 条件覆盖 Slots

**描述**：同类条件在 refine 时被新值覆盖。

**规则**：
- 新 Slot 与已有 Slot 存在同类（同一 key） → 新值覆盖旧值
- 示例：`已有 {count: 10}` + `新增 {count: 20}` → `{count: 20}`
- 覆盖后返回 `SlotMergeResult`（merged_slots, merge_type="覆盖", changed_fields=["count"]）

**关联**：PRD FR-006, 05-business-rules.md BR-05

---

## REQ-006: 排除条件处理

**描述**：否定表达（"不要XX"）追加到 exclude 列表，不覆盖已有排除项。

**规则**：
- 排除条件存储在 `last_filters.exclude` 列表中
- 每次新增排除条件 → 追加到列表尾部
- 示例：`已有 exclude: ["外包"]` + `新增 exclude: "留学生"` → `exclude: ["外包", "留学生"]`
- exclude 列表内的项不重复（相同值不重复追加）
- 新 search 时清空整个 exclude 列表

**关联**：PRD FR-006, 05-business-rules.md BR-05

---

## REQ-007: 条件重置

**描述**：当用户发起新的 `recruitment.search` 时，所有历史 filters 重置。

**规则**：
- reset_state 将 last_filters 清空为 `{}`
- reset_state 将 last_candidates 清空为 `[]`
- reset_state 将 last_query 清空为 `{}`
- reset_state 将 last_sort_by 清空为 `None`
- reset_state 不清空 turn_count 和 intent_history（这两个字段全生命周期累积）
- 重置后返回清空后的 ConversationState

**关联**：PRD FR-006, 05-business-rules.md BR-07

---

## REQ-008: 检索范围决策

**描述**：refine 时根据条件变化类型，向调用方建议检索范围。

**决策规则**：

| 条件变化类型 | 建议检索范围 | 说明 |
|-------------|-------------|------|
| 仅修改排序/数量 | `scope: "within_candidates"` | 在 last_candidates 内重新排序 |
| 追加过滤条件 | `scope: "within_candidates_fallback"` | 先在 last_candidates 内过滤，为空则扩大到全库 |
| 修改核心条件（job_title/skills） | `scope: "full_search"` | 重新全库检索 |
| 排除条件（exclude） | `scope: "within_candidates"` | 在 last_candidates 内过滤 |

**输出**：
- `SlotMergeResult.search_scope` 字段：`"full_search"` | `"within_candidates"` | `"within_candidates_fallback"`

**关联**：05-business-rules.md BR-06

---

## REQ-009: 对话历史持久化

**描述**：所有 Conversation 和 Message 必须持久化到 MongoDB。

**规则**：
- Conversation 和 Message 分别存储在 `conversations` 和 `messages` 集合中
- ConversationState 嵌入在 conversations 集合的 document 中
- 每次 add_message / merge_slots / reset_state 后立即写入 MongoDB
- MongoDB 不可用时降级到内存 dict 存储（不持久化），并记录 WARNING 日志

**关联**：PRD FR-007, 05-business-rules.md BR-09

---

## REQ-010: 对话列表查询

**描述**：支持按 user_id 查询该用户的所有对话列表，按 updated_at 倒序排列。

**输入**：
- `user_id: str`
- `limit: int = 20` — 每页条数
- `offset: int = 0` — 偏移量

**输出**：
- `list[Conversation]` — 按 updated_at 降序

**规则**：
- 只返回 status="active" 的对话
- 返回结果包含 conversation_id, title, turn_count, created_at, updated_at
- 支持分页（limit + offset）

**关联**：PRD FR-007

---

## REQ-011: 对话删除

**描述**：支持软删除对话（status 从 "active" 改为 "deleted"）。

**输入**：
- `conversation_id: str`

**输出**：
- `bool` — 删除是否成功

**规则**：
- 软删除，不物理删除 MongoDB document
- 软删除后对话不出现在 list_conversations 结果中
- conversation_id 不存在时返回 False

**关联**：-

---

## REQ-012: last_candidates 引用

**描述**：支持从 last_candidates 中按位置（0-based）或姓名定位候选人。

**输入**：
- `conversation_id: str`
- `ref: str` — 引用方式，如 `"last_candidates[0]"` 或候选人姓名 `"张三"`

**输出**：
- `Resume` 引用信息（candidate_id, candidate_name, rank, score）

**规则**：
- 按位置引用：解析 `last_candidates[N]`，N 为 0-based 索引
- 按姓名引用：在 last_candidates 中模糊匹配 name 字段
- 姓名匹配到多人时返回候选列表（不自动选择）
- 姓名匹配到 0 人时返回 None
- last_candidates 为空时返回 None

**关联**：PRD FR-006, 05-business-rules.md BR-14

---
## v1.2-data-pipeline 新增 (2026-06-26)
| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-008 | FR-006 | Session TTL 检查: get_session() 必须比对 last_active_at，超时返回 None | P0 |
| REQ-009 | FR-006 | refine NARROW 分支: 在上次候选集中执行语义过滤（非全库检索），结果为空时降级为 FULL | P0 |
| REQ-010 | FR-006 | SessionState 持久化 last_intent 字段，get_conversation_context 返回 last_intent | P1 |
| REQ-011 | FR-006 | CandidateSlot 新增 candidate_name 字段，lookup 优先用名字匹配 | P2 |

## v1.3-data-pipeline 新增 (2026-06-26)
| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-012 | FR-006 | MetadataFilter 必须在 MongoDB enrichment 填充 metadata（city/education/years_of_experience/skills）之后再执行，而非之前 | P0 |
| REQ-013 | FR-006 | efine() NARROW 分支优先通过 Milvus 表达式 esume_id in [...] 在向量层过滤，而非拉全量后再过滤 | P1 |
