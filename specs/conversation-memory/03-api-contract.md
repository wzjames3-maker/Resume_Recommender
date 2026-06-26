<!-- Module: conversation-memory -->
<!-- Spec Layer: 03 - API Contract -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 内部接口契约：Conversation Memory（对话记忆模块）

## 接口总览

本模块提供 **内部接口**（不对外暴露），供 intent-router、recommendation-engine、api-layer 通过函数调用使用。

| # | 接口 | 调用方 | 说明 |
|---|------|--------|------|
| 1 | create_conversation | api-layer | 创建新对话 |
| 2 | get_conversation | api-layer / intent-router | 获取对话信息 |
| 3 | add_message | intent-router / recommendation-engine | 保存消息 |
| 4 | get_state | intent-router | 获取对话状态 |
| 5 | merge_slots | intent-router | 合并 Slots |
| 6 | reset_state | intent-router | 重置对话状态 |
| 7 | get_last_candidates | recommendation-engine | 获取上次推荐 |
| 8 | resolve_candidate_ref | intent-router / recommendation-engine | 解析候选人引用 |
| 9 | list_conversations | api-layer | 查询对话列表 |
| 10 | delete_conversation | api-layer | 删除对话 |

---

## 接口 1: create_conversation

创建新的 Conversation 会话。

### 签名

```python
async def create_conversation(user_id: str) -> Conversation
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | str | 是 | 用户标识（JWT 中的 user_id） |

### 返回值

```python
Conversation(
    conversation_id="550e8400-e29b-41d4-a716-446655440000",
    user_id="user_001",
    title="对话 2026-06-23 14:30",
    turn_count=0,
    status="active",
    created_at=datetime(2026, 6, 23, 14, 30, 0),
    updated_at=datetime(2026, 6, 23, 14, 30, 0)
)
```

### 行为

1. 生成 UUID v4 作为 conversation_id
2. 自动生成 title: `"对话 {YYYY-MM-DD HH:mm}"`
3. 初始化 ConversationState（全部为默认空值）
4. 写入 MongoDB `conversations` 集合
5. 返回 Conversation 对象

### 异常

| 场景 | 处理 |
|------|------|
| MongoDB 不可用 | 降级到内存存储，记录 WARNING 日志 |

---

## 接口 2: get_conversation

获取指定 Conversation。

### 签名

```python
async def get_conversation(conversation_id: str) -> Optional[Conversation]
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | str | 是 | 会话 ID |

### 返回值

- 存在：`Conversation` 对象
- 不存在：`None`

### 行为

1. 从 MongoDB `conversations` 集合查询 `_id = conversation_id`
2. 排除 `status = "deleted"` 的记录
3. 反序列化为 Conversation 对象

---

## 接口 3: add_message

保存一条对话消息并更新对话状态。

### 签名

```python
async def add_message(
    conversation_id: str,
    role: str,
    content: str,
    intent: str,
    slots: dict,
    confidence: Optional[float] = None,
    tool_calls: Optional[list] = None,
    latency_ms: Optional[int] = None,
    tokens: Optional[int] = None,
) -> Message
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | str | 是 | 会话 ID |
| role | str | 是 | "user" 或 "assistant" |
| content | str | 是 | 消息文本 |
| intent | str | 是 | 识别的意图 |
| slots | dict | 是 | 提取的 Slots（快照） |
| confidence | float | 否 | 意图置信度 |
| tool_calls | list | 否 | 工具调用列表 |
| latency_ms | int | 否 | 响应耗时 |
| tokens | int | 否 | 消耗 Token 数 |

### 返回值

```python
Message(
    message_id="...",
    conversation_id="...",
    role="user",
    content="找5年Java工程师",
    intent="recruitment.search",
    confidence=0.95,
    slots={"job_title": "Java工程师", "experience": 5, ...},
    created_at=datetime.utcnow()
)
```

### 行为

1. 生成 UUID v4 作为 message_id
2. 写入 MongoDB `messages` 集合
3. 递增 conversation.turn_count（通过 `find_one_and_update` 原子操作）
4. 如果 role="user"，追加 intent 到 state.intent_history
5. 更新 conversation.updated_at
6. 返回 Message 对象

### 异常

| 场景 | 处理 |
|------|------|
| conversation_id 不存在 | 抛出 `ConversationNotFoundError` |
| MongoDB 不可用 | 降级到内存存储，记录 WARNING 日志 |

---

## 接口 4: get_state

获取指定 Conversation 的 ConversationState。

### 签名

```python
async def get_state(conversation_id: str) -> ConversationState
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | str | 是 | 会话 ID |

### 返回值

```python
ConversationState(
    last_query={"job_title": "Java工程师", "skills": ["Java"], ...},
    last_filters={"city": "杭州", "education": "985", ...},
    last_candidates=[
        CandidateRef(candidate_id="...", candidate_name="张三", rank=1, score=92.5),
        ...
    ],
    last_sort_by="score",
    turn_count=5,
    intent_history=["recruitment.search", "recruitment.refine", ...]
)
```

### 行为

1. 从 MongoDB 查询 conversation.state 字段
2. 反序列化为 ConversationState 对象
3. 如果 conversation 不存在，抛出 `ConversationNotFoundError`

---

## 接口 5: merge_slots

合并新 Slots 到对话状态的 last_filters。

### 签名

```python
async def merge_slots(
    conversation_id: str,
    new_slots: dict,
    changed_core_fields: Optional[List[str]] = None,
) -> SlotMergeResult
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | str | 是 | 会话 ID |
| new_slots | dict | 是 | 本轮新增的 Slots |
| changed_core_fields | list[str] | 否 | 本轮变更的核心字段列表（如 ["job_title"]），影响 search_scope |

### 返回值

```python
SlotMergeResult(
    merged_slots={"city": "杭州", "education": "985", "gender": "女", ...},
    merge_type=MergeType.INCREMENTAL,
    changed_fields=["gender"],
    search_scope=SearchScope.WITHIN_CANDIDATES_FALLBACK
)
```

### 行为

1. 获取当前 ConversationState
2. 根据合并规则处理每个 new_slot：
   - **新 key** → 追加到 last_filters（增量）
   - **已有 key** → 用新值覆盖旧值（覆盖）
   - **exclude key** → 追加到 exclude 列表（排除条件，去重）
3. 判断 merge_type：
   - 全部为新 key → `INCREMENTAL`
   - 存在已有 key 被覆盖 → `OVERWRITE`（如有新 key 则为 `INCREMENTAL`）
4. 判断 search_scope：
   - changed_core_fields 包含 job_title 或 skills → `FULL_SEARCH`
   - 仅排除条件 → `WITHIN_CANDIDATES`
   - 仅 Query Slot（count/sort_by 等）被覆盖 → `WITHIN_CANDIDATES`
   - 其他 → `WITHIN_CANDIDATES_FALLBACK`
5. 更新 MongoDB 中的 state.last_filters
6. 返回 SlotMergeResult

---

## 接口 6: reset_state

重置对话状态（新 search 时调用）。

### 签名

```python
async def reset_state(conversation_id: str) -> ConversationState
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | str | 是 | 会话 ID |

### 返回值

重置后的 `ConversationState`（last_query, last_filters, last_candidates 全部清空）

### 行为

1. 更新 MongoDB 中的 state：
   - `last_query` → `{}`
   - `last_filters` → `{}`
   - `last_candidates` → `[]`
   - `last_sort_by` → `None`
   - `turn_count` 和 `intent_history` 不清空
2. 返回更新后的 ConversationState

---

## 接口 7: get_last_candidates

获取上次推荐的候选人列表。

### 签名

```python
async def get_last_candidates(conversation_id: str) -> List[CandidateRef]
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | str | 是 | 会话 ID |

### 返回值

```python
[
    CandidateRef(candidate_id="resume_001", candidate_name="张三", rank=1, score=92.5),
    CandidateRef(candidate_id="resume_002", candidate_name="李四", rank=2, score=88.3),
]
```

### 行为

1. 从 ConversationState 中提取 last_candidates
2. 如果 conversation 不存在，抛出 `ConversationNotFoundError`
3. 如果 last_candidates 为空，返回空列表 `[]`

---

## 接口 8: resolve_candidate_ref

从 last_candidates 中解析候选人引用。

### 签名

```python
async def resolve_candidate_ref(
    conversation_id: str,
    ref: str,
) -> Union[CandidateRef, List[CandidateRef], None]
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | str | 是 | 会话 ID |
| ref | str | 是 | 引用方式："last_candidates[N]" 或候选人姓名 |

### 返回值

| 场景 | 返回 |
|------|------|
| 按位置匹配成功 | `CandidateRef` |
| 按姓名匹配 1 人 | `CandidateRef` |
| 按姓名匹配多人 | `List[CandidateRef]`（候选列表） |
| 按姓名匹配 0 人 | `None` |
| last_candidates 为空 | `None` |
| 索引越界 | `None` |

### 行为

1. 获取 last_candidates
2. 如果 ref 格式为 `last_candidates[N]`：
   - 解析 N（0-based 索引）
   - 返回 `last_candidates[N]`，越界返回 None
3. 如果 ref 为姓名字符串：
   - 在 last_candidates 中匹配 `candidate_name`
   - 精确匹配优先
   - 精确匹配无结果时尝试包含匹配（"张" 匹配 "张三"、"张四"）
   - 匹配 1 人 → 返回 CandidateRef
   - 匹配多人 → 返回 List[CandidateRef]
   - 匹配 0 人 → 返回 None

---

## 接口 9: list_conversations

查询用户对话列表。

### 签名

```python
async def list_conversations(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
) -> List[Conversation]
```

### 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| user_id | str | 是 | - | 用户标识 |
| limit | int | 否 | 20 | 每页条数 |
| offset | int | 否 | 0 | 偏移量 |

### 返回值

`List[Conversation]` — 按 updated_at 降序，只返回 status="active" 的对话

### 行为

1. 查询 MongoDB：`{user_id: user_id, status: "active"}`
2. 按 `updated_at` 降序排序
3. 应用 `skip(offset).limit(limit)` 分页

---

## 接口 10: delete_conversation

软删除对话。

### 签名

```python
async def delete_conversation(conversation_id: str) -> bool
```

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | str | 是 | 会话 ID |

### 返回值

- `True` — 删除成功
- `False` — conversation_id 不存在

### 行为

1. 更新 MongoDB：`{status: "active"}` → `{status: "deleted"}`
2. 如果 document 不存在，返回 False
3. 不物理删除 messages（保留审计记录）

---

## 自定义异常

```python
class ConversationNotFoundError(Exception):
    """conversation_id 不存在或已删除"""
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        super().__init__(f"Conversation not found: {conversation_id}")
```

---

## 调用时序示例

### 多轮对话完整流程

```
api-layer                intent-router           conversation-memory       recommendation-engine
   │                          │                          │                          │
   │ create_conversation()     │                          │                          │
   │─────────────────────────>│                          │                          │
   │                          │                          │                          │
   │                          │ get_state(conv_id)       │                          │
   │                          │─────────────────────────>│                          │
   │                          │<─────── ConversationState│                          │
   │                          │                          │                          │
   │                          │ add_message(user)        │                          │
   │                          │─────────────────────────>│                          │
   │                          │                          │                          │
   │                          │─────── slots ──────────────────────────────────────>│
   │                          │                          │                          │
   │                          │                          │ update last_candidates    │
   │                          │                          │<─────────────────────────│
   │                          │                          │                          │
   │                          │ add_message(assistant)   │                          │
   │                          │─────────────────────────>│                          │
   │                          │                          │                          │
   │  ════ 用户输入修正条件 ════                          │                          │
   │                          │                          │                          │
   │                          │ get_state(conv_id)       │                          │
   │                          │─────────────────────────>│                          │
   │                          │<─────── ConversationState│                          │
   │                          │                          │                          │
   │                          │ merge_slots(new_slots)   │                          │
   │                          │─────────────────────────>│                          │
   │                          │<─────── SlotMergeResult  │                          │
   │                          │                          │                          │
   │                          │─────── merged_slots + search_scope ───────────────>│
   │                          │                          │                          │
```
