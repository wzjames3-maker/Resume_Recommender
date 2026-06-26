<!-- Module: conversation-memory -->
<!-- Spec Layer: 05 - Edge Cases -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 边界情况与异常处理：Conversation Memory（对话记忆模块）

## 边界情况总览

| ID | 场景 | 严重程度 | 处理策略 |
|----|------|----------|----------|
| EC-001 | 无上文时收到 refine | 高 | 返回引导提示 |
| EC-002 | conversation_id 不存在 | 高 | 返回 404 |
| EC-003 | last_candidates 为空时收到 lookup | 高 | 返回引导提示 |
| EC-004 | 并发写入同一 conversation | 中 | 原子操作 |
| EC-005 | Slot 合并后条件互相矛盾 | 低 | 后者覆盖 |
| EC-006 | 对话超长（>100 轮） | 中 | 截断早期消息 |
| EC-007 | MongoDB 连接失败 | 高 | 降级到内存 |

---

## EC-001: 无上文时收到 refine

**场景**：用户在没有执行过 `recruitment.search` 的情况下，直接输入条件修正语句（如"女生呢"、"学历高一点"）。

**触发条件**：
- intent = `recruitment.refine`
- last_query 为空（`{}`）
- 未曾执行过 recruitment.search

**处理策略**：

```
IF intent == "recruitment.refine" AND state.last_query == {}:
    RETURN {
        "status": "no_context",
        "message": "请先描述您的招聘需求，例如"找5年Java工程师"",
        "suggestion": "recruitment.search"
    }
```

**用户感知**：
- 系统返回引导性提示："请先描述您的招聘需求"
- 不执行 merge_slots 和推荐检索
- 不创建错误日志（这是正常业务场景，不是系统错误）

**关联**：PRD UC-002 异常流程 EF-001

---

## EC-002: conversation_id 不存在

**场景**：调用方传入的 conversation_id 在 MongoDB 中不存在或已被软删除。

**触发条件**：
- get_conversation(conversation_id) 返回 None
- get_state(conversation_id) 抛出 ConversationNotFoundError
- add_message(conversation_id, ...) 时 conversation 不存在

**处理策略**：

```
# get_conversation
IF conversation not found:
    RETURN None  # 上层决定是否返回 404

# get_state / add_message / merge_slots / reset_state
IF conversation not found:
    RAISE ConversationNotFoundError(conversation_id)
```

**上层处理（api-layer）**：

```json
{
    "error": "CONVERSATION_NOT_FOUND",
    "message": "对话不存在或已删除",
    "conversation_id": "xxx"
}
```

HTTP Status: `404 Not Found`

**关联**：PRD 附录 B 错误码

---

## EC-003: last_candidates 为空时收到 lookup

**场景**：用户在没有推荐结果的情况下，尝试查看候选人详情（如"第一个人是谁"）。

**触发条件**：
- intent = `candidate.lookup`
- last_candidates 为空（`[]`）

**处理策略**：

```
# resolve_candidate_ref
IF candidates is empty:
    RETURN None  # 上层返回引导提示
```

**上层处理（intent-router）**：

```json
{
    "status": "no_candidates",
    "message": "暂无推荐候选人，请先进行候选人检索",
    "suggestion": "recruitment.search"
}
```

**关联**：PRD UC-003 异常流程 EF-002

---

## EC-004: 并发写入同一 conversation

**场景**：同一用户的多个请求并发写入同一个 conversation（如快速连续发送多条消息）。

**触发条件**：
- 两个或多个请求同时调用 add_message / merge_slots / reset_state
- 目标 conversation_id 相同

**风险**：
- 后写入的请求覆盖先写入的 state 更新（Lost Update）
- turn_count 不准确（并发递增丢失）

**处理策略**：使用 MongoDB `find_one_and_update` 原子操作。

```python
# turn_count 原子递增
result = await db.conversations.find_one_and_update(
    {"_id": conversation_id, "status": "active"},
    {"$inc": {"turn_count": 1}, "$set": {"updated_at": datetime.utcnow()}},
    return_document=ReturnDocument.AFTER
)

# state 原子更新（merge_slots）
result = await db.conversations.find_one_and_update(
    {"_id": conversation_id, "status": "active"},
    {"$set": {"state.last_filters": merged_filters, "updated_at": datetime.utcnow()}},
    return_document=ReturnDocument.AFTER
)
```

**约束**：
- 不使用乐观锁（Version 字段），V1 场景并发量低（NFR-005: 50 并发用户）
- `find_one_and_update` 是 MongoDB 单 document 原子操作，足以保证正确性
- 如果未来并发量增大，可引入乐观锁（V2）

**关联**：REQ-003, REQ-009

---

## EC-005: Slot 合并后条件互相矛盾

**场景**：refine 时新旧条件产生矛盾（如先说"5年以上"，后说"3年"）。

**触发条件**：
- merge_slots 中新值与旧值逻辑冲突
- 典型矛盾：
  - experience: 5 → 3（年限减少）
  - education: "硕士" → "本科"（学历降低）
  - city: "杭州" → "北京"（城市变更）

**处理策略**：后者覆盖，不做矛盾检测。

```
# 不做任何矛盾检测或警告
state.last_filters["experience"] = new_experience  # 直接覆盖
```

**理由**：
1. 矛盾检测需要语义理解（如"5年"和"3年"哪个是最终意图），实现成本高
2. 用户修正条件是明确意图表达，系统应信任用户
3. 如果用户说"3年"，他们确实想从"5年"改为"3年"
4. 覆盖行为符合用户预期（"我说了新的，就是新的"）

**示例**：

```
Turn 1: "找5年Java工程师"
  → last_filters = {experience: 5, experience_op: ">="}

Turn 2: "3年的有吗"
  → last_filters = {experience: 3, experience_op: ">="}  ← 直接覆盖，不警告
```

**关联**：RULE-003

---

## EC-006: 对话超长（>100 轮）

**场景**：对话轮次超过 100 轮，导致 messages 集合数据膨胀、查询变慢。

**触发条件**：
- conversation.turn_count > 100

**处理策略**：分两级处理。

### 第一级：50 轮警告

```
IF turn_count > 50:
    RETURN warning: {
        "code": "CONVERSATION_TOO_LONG",
        "message": "对话已超过 50 轮，建议创建新对话",
        "turn_count": turn_count
    }
```

- 不阻断操作，仅返回 warning
- 上层可选择展示"建议新建对话"按钮

### 第二级：100 轮截断

```
IF turn_count > 100:
    # 保留最近 50 轮消息
    cutoff_turn = turn_count - 50
    cutoff_message = await db.messages.find_one(
        {"conversation_id": conversation_id},
        sort=[("created_at", 1)],
        skip=cutoff_turn
    )

    await db.messages.delete_many({
        "conversation_id": conversation_id,
        "created_at": {"$lt": cutoff_message["created_at"]}
    })

    # 更新 turn_count
    await db.conversations.update_one(
        {"_id": conversation_id},
        {"$set": {"turn_count": 50}}
    )

    logger.warning(f"Conversation {conversation_id} truncated: {turn_count} -> 50")
```

**约束**：
- 截断只删除 messages，ConversationState 不受影响
- 截断不可逆
- 截断操作记录 WARNING 日志

**关联**：RULE-008, RULE-008b

---

## EC-007: MongoDB 连接失败

**场景**：MongoDB 服务不可用（连接超时、认证失败、服务宕机）。

**触发条件**：
- pymongo 抛出 `ConnectionFailure` / `ServerSelectionTimeoutError`
- 连接池耗尽

**处理策略**：降级到内存存储。

```python
class ConversationMemoryStore:
    def __init__(self, mongodb_uri: str):
        self._mongo_client = None
        self._memory_store: Dict[str, dict] = {}  # 降级存储
        self._is_degraded = False

    async def _get_collection(self, name: str):
        try:
            if self._mongo_client is None:
                self._mongo_client = AsyncIOMotorClient(mongodb_uri)
            # 尝试 ping 测试连接
            await self._mongo_client.admin.command("ping")
            self._is_degraded = False
            return self._mongo_client[name]
        except Exception as e:
            if not self._is_degraded:
                logger.warning(f"MongoDB unavailable, falling back to in-memory store: {e}")
                self._is_degraded = True
            return None
```

**降级行为**：

| 操作 | 正常模式 | 降级模式 |
|------|----------|----------|
| create_conversation | 写入 MongoDB | 写入内存 dict |
| get_conversation | 读 MongoDB | 读内存 dict |
| add_message | 写入 MongoDB messages + 更新 conversation | 写入内存 list |
| merge_slots | 更新 MongoDB state | 更新内存 state |
| list_conversations | 查询 MongoDB | 从内存 dict 过滤 |

**约束**：
- 降级后数据不持久化（进程重启丢失）
- 降级时所有写操作记录 WARNING 日志
- MongoDB 恢复后，新请求自动切回 MongoDB（不自动同步降级期间的数据）
- 降级状态通过 health check 接口暴露（api-layer 可查询）

**关联**：REQ-009

---

## 边界情况优先级排序

### P0（必须处理）

| ID | 场景 | 理由 |
|----|------|------|
| EC-001 | 无上文时收到 refine | 直接影响用户体验 |
| EC-002 | conversation_id 不存在 | 直接影响 API 正确性 |
| EC-003 | last_candidates 为空时 lookup | 直接影响用户体验 |
| EC-004 | 并发写入 | 影响数据一致性 |
| EC-007 | MongoDB 连接失败 | 影响系统可用性 |

### P1（应该处理）

| ID | 场景 | 理由 |
|----|------|------|
| EC-006 | 对话超长 | 影响性能和存储 |

### P2（可延后处理）

| ID | 场景 | 理由 |
|----|------|------|
| EC-005 | 条件矛盾 | 当前策略（后者覆盖）已足够
