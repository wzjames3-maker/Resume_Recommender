<!-- Module: conversation-memory -->
<!-- Spec Layer: 04 - Business Rules -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 业务规则：Conversation Memory（对话记忆模块）

## 规则总览

| 规则 | 说明 | 来源 |
|------|------|------|
| RULE-001 | 新 search 时重置所有 last_filters | BR-07 |
| RULE-002 | refine 时增量合并新条件到 last_filters | BR-05 |
| RULE-003 | 同类条件后者覆盖前者 | BR-05 |
| RULE-004 | 排除条件追加到 exclude 列表，不覆盖 | BR-05 |
| RULE-005 | last_candidates 在每次推荐后更新 | Domain Model |
| RULE-006 | candidate.lookup 按位置或姓名匹配 | BR-14 |
| RULE-007 | 姓名匹配到多人时返回候选列表 | BR-14 |
| RULE-008 | 对话超过 50 轮自动创建新对话 | 设计决策 |
| RULE-009 | 对话状态持久化到 MongoDB | BR-09 |
| RULE-010 | 会话 TTL 管理：Redis EXPIRE 滑动窗口 1800s + MongoDB TTL 硬过期 86400s | 设计决策 |

---

## RULE-001: 新 search 时重置所有 last_filters

**来源**：05-business-rules.md BR-07

**规则**：当用户发起新的 `recruitment.search` 时，所有历史 filters 重置，开始全新查询。

**执行逻辑**：

```
IF intent == "recruitment.search":
    state.last_query = {}
    state.last_filters = {}
    state.last_candidates = []
    state.last_sort_by = None
    # 不清空 turn_count 和 intent_history
```

**示例**：

```
Turn 1: "找Java工程师"     → last_filters = {skills: ["Java"]}
Turn 2: "女生呢"           → last_filters = {skills: ["Java"], gender: "女"}
Turn 3: "找算法工程师"     → last_filters = {} → {job_title: "算法工程师"}
                              （所有之前的条件全部重置）
```

**约束**：
- reset_state 只在 `recruitment.search` 时调用，不适用于其他 intent
- turn_count 和 intent_history 不受 reset 影响（全生命周期累积）

---

## RULE-002: refine 时增量合并新条件到 last_filters

**来源**：05-business-rules.md BR-05（增量合并部分）

**规则**：当 intent 为 `recruitment.refine` 时，新条件追加到已有 last_filters 中（新 key 直接追加）。

**执行逻辑**：

```
IF intent == "recruitment.refine":
    FOR each key, value in new_slots:
        IF key not in state.last_filters:
            state.last_filters[key] = value  # 增量追加
```

**示例**：

```
已有 last_filters:
{
  "job_title": "Java工程师",
  "skills": ["Java"],
  "experience": 5,
  "experience_op": ">=",
  "city": "杭州",
  "education": "985"
}

新增 slots: { "gender": "女" }

合并后 last_filters:
{
  "job_title": "Java工程师",
  "skills": ["Java"],
  "experience": 5,
  "experience_op": ">=",
  "city": "杭州",
  "education": "985",
  "gender": "女"        ← 新增
}
```

**约束**：
- 仅在 `recruitment.refine` 时执行，不适用于 `recruitment.search`
- 合并后必须返回 SlotMergeResult，供下游决策检索范围

---

## RULE-003: 同类条件后者覆盖前者

**来源**：05-business-rules.md BR-05（条件覆盖部分）

**规则**：refine 时如果新 Slot 与已有 Slot 是同一个 key，新值覆盖旧值。

**执行逻辑**：

```
IF intent == "recruitment.refine":
    FOR each key, value in new_slots:
        IF key in state.last_filters AND key != "exclude":
            state.last_filters[key] = value  # 覆盖
```

**示例**：

```
场景 A：数量覆盖
已有 last_filters: { ..., "count": 10 }
新增 slots: { "count": 20 }
结果: { ..., "count": 20 }  ← 20 覆盖 10

场景 B：年限覆盖（矛盾条件）
已有 last_filters: { "experience": 5, "experience_op": ">=" }
新增 slots: { "experience": 3, "experience_op": ">=" }
结果: { "experience": 3, "experience_op": ">=" }  ← 3 覆盖 5

场景 C：排序覆盖
已有 last_filters: { "sort_by": "score" }
新增 slots: { "sort_by": "experience" }
结果: { "sort_by": "experience" }  ← experience 覆盖 score
```

**约束**：
- 覆盖是全量替换，不是数值运算（"5年"和"3年"不取平均值，直接用 3 年）
- exclude 列表不适用覆盖规则，使用 RULE-004

---

## RULE-004: 排除条件追加到 exclude 列表，不覆盖

**来源**：05-business-rules.md BR-05（排除条件部分）

**规则**：否定表达（"不要XX"）追加到 `last_filters.exclude` 列表中，不覆盖已有排除项。

**执行逻辑**：

```
IF intent == "recruitment.refine":
    IF "exclude" in new_slots:
        IF "exclude" not in state.last_filters:
            state.last_filters["exclude"] = []
        FOR each item in new_slots["exclude"]:
            IF item not in state.last_filters["exclude"]:
                state.last_filters["exclude"].append(item)  # 追加，去重
```

**示例**：

```
场景 A：首次排除
已有 last_filters: { "skills": ["Java"] }
新增 slots: { "exclude": ["外包"] }
结果: { "skills": ["Java"], "exclude": ["外包"] }

场景 B：追加排除
已有 last_filters: { "skills": ["Java"], "exclude": ["外包"] }
新增 slots: { "exclude": ["留学生"] }
结果: { "skills": ["Java"], "exclude": ["外包", "留学生"] }

场景 C：重复排除（去重）
已有 last_filters: { "exclude": ["外包"] }
新增 slots: { "exclude": ["外包"] }
结果: { "exclude": ["外包"] }  ← 不重复追加
```

**约束**：
- exclude 列表中的项不会被 RULE-003 覆盖
- 新 search 时整个 exclude 列表随 last_filters 一起清空（RULE-001）

---

## RULE-005: last_candidates 在每次推荐后更新

**来源**：04-domain-model.md Recommendation 实体

**规则**：每次推荐查询完成后（无论 search 还是 refine），更新 last_candidates。

**执行逻辑**：

```
# 推荐完成后由 recommendation-engine 调用
state.last_candidates = [
    CandidateRef(
        candidate_id=item.resume_id,
        candidate_name=item.candidate_name,
        rank=item.rank,
        score=item.score
    )
    for item in recommendation.items
]
state.last_sort_by = current_sort_by
```

**示例**：

```
推荐结果: [
    { resume_id: "R001", candidate_name: "张三", rank: 1, score: 92.5 },
    { resume_id: "R002", candidate_name: "李四", rank: 2, score: 88.3 },
    { resume_id: "R003", candidate_name: "王五", rank: 3, score: 85.1 },
]

更新后 state.last_candidates = 上述列表（精简为 candidate_id, name, rank, score）
```

**约束**：
- last_candidates 只存储精简信息，不存储完整 Resume 数据
- last_candidates 最多保留 100 条（PRD count 上限为 100）
- 更新操作通过 `find_one_and_update` 原子完成

---

## RULE-006: candidate.lookup 按位置或姓名匹配

**来源**：05-business-rules.md BR-14

**规则**：candidate.lookup 时从 last_candidates 中定位候选人，支持两种引用方式。

**引用方式**：

| 引用格式 | 匹配方式 | 示例 |
|----------|----------|------|
| `last_candidates[N]` | 按 0-based 索引 | "第一个人" → `last_candidates[0]` |
| 姓名字符串 | 按 name 字段匹配 | "张三" → 在 last_candidates 中找 name="张三" |

**解析逻辑**：

```
FUNCTION resolve_candidate_ref(conversation_id, ref):
    candidates = get_last_candidates(conversation_id)

    IF candidates is empty:
        RETURN None

    IF ref matches pattern "last_candidates[(\d+)]":
        index = extract_number(ref)
        IF index < len(candidates):
            RETURN candidates[index]
        ELSE:
            RETURN None  # 索引越界

    ELSE:
        # 姓名匹配
        exact_matches = [c for c in candidates if c.candidate_name == ref]
        IF len(exact_matches) == 1:
            RETURN exact_matches[0]
        ELIF len(exact_matches) > 1:
            RETURN exact_matches  # 多人匹配，返回列表
        ELSE:
            # 模糊匹配（包含关系）
            fuzzy_matches = [c for c in candidates if ref in c.candidate_name]
            IF len(fuzzy_matches) == 1:
                RETURN fuzzy_matches[0]
            ELIF len(fuzzy_matches) > 1:
                RETURN fuzzy_matches
            ELSE:
                RETURN None  # 无匹配
```

**中文数字映射**：

| 中文 | 索引 |
|------|------|
| 第一 / 第一个 | 0 |
| 第二 / 第二个 | 1 |
| 第三 / 第三个 | 2 |
| ... | ... |
| 最后 / 最后一个 | len(candidates) - 1 |

**约束**：
- 索引为 0-based（"第一个人" = index 0）
- 姓名匹配优先精确匹配，再模糊匹配
- last_candidates 为空时返回 None（上层返回"请先搜索候选人"提示）

---

## RULE-007: 姓名匹配到多人时返回候选列表

**来源**：05-business-rules.md BR-14

**规则**：当按姓名匹配到多个候选人时，不自动选择，而是返回候选列表让上层引导用户选择。

**示例**：

```
last_candidates: [
    { name: "张三", candidate_id: "R001" },
    { name: "张四", candidate_id: "R002" },
    { name: "李四", candidate_id: "R003" },
]

用户: "看看张三/张四的简历"
ref = "张"

匹配结果: [张三, 张四]（模糊匹配，"张" 包含在两个姓名中）

→ 返回列表，上层提示"找到多个匹配，请选择：1. 张三  2. 张四"
```

**约束**：
- 返回列表而非单个结果时，上层必须展示选择界面
- 如果用户后续说"第一个"，应使用 `last_candidates[N]` 方式引用（需结合上下文理解）

---

## RULE-008: 对话超过 50 轮自动创建新对话

**来源**：设计决策（防止状态膨胀）

**规则**：当对话轮次（turn_count）超过 50 轮时，系统应建议创建新对话。

**执行逻辑**：

```
# 每次 add_message 后检查
IF conversation.turn_count > 50:
    RETURN warning: "对话已超过 50 轮，建议创建新对话以保持最佳体验"
```

**行为**：
- 不强制创建新对话（用户可选择继续）
- 返回 warning 提示，由上层决定是否展示
- turn_count > 100 时截断早期消息（RULE-008b）

**RULE-008b: 对话超长截断**

```
IF conversation.turn_count > 100:
    # 保留最近 50 轮消息，标记早期消息为 truncated
    DELETE messages WHERE conversation_id = X AND created_at < cutoff_time
    # cutoff_time = 第 51 轮消息的 created_at
    SET conversation.turn_count = 50
```

**约束**：
- 截断只删除 messages，不影响 ConversationState（state 始终反映最新状态）
- 截断操作记录 WARNING 日志
- 截断不可逆（消息被物理删除）

---

## RULE-009: 对话状态持久化到 MongoDB

**来源**：05-business-rules.md BR-09

**规则**：所有 Conversation 和 Message 必须持久化到 MongoDB，保证跨请求恢复。

**执行逻辑**：

```
# 所有写操作遵循以下模式
async def persist_state(conversation_id, state_updates):
    TRY:
        await db.conversations.update_one(
            {"_id": conversation_id},
            {"$set": {"state": state_updates, "updated_at": datetime.utcnow()}}
        )
    EXCEPT ConnectionError:
        logger.warning(f"MongoDB unavailable, falling back to in-memory: {conversation_id}")
        memory_store.update(conversation_id, state_updates)
```

**持久化时机**：

| 操作 | 持久化内容 |
|------|-----------|
| create_conversation | 插入 conversation document |
| add_message | 插入 message document + 更新 conversation.turn_count |
| merge_slots | 更新 conversation.state.last_filters |
| reset_state | 更新 conversation.state（清空 fields） |
| update last_candidates | 更新 conversation.state.last_candidates |

**降级策略**：
- MongoDB 不可用时降级到内存 dict 存储
- 内存存储不保证持久化（进程重启丢失）
- 降级时记录 WARNING 日志，包含 conversation_id
- MongoDB 恢复后不自动同步内存数据（新请求使用 MongoDB）

**约束**：
- 所有写操作使用 `find_one_and_update` 保证原子性
- 不使用事务（单 document 更新不需要）
- MongoDB 连接字符串从环境变量 `MONGODB_URI` 读取
---

## RULE-010: 会话 TTL 管理（Redis 滑动窗口）

**来源**: 设计决策（引入 Redis）

**规则描述**: 会话存活时间通过 Redis EXPIRE 精确管理，实现真正的滑动窗口过期。

**执行逻辑**:

```text
1. 创建会话时：
   - Redis SET conversation:{id}:state <serialized_state> EX 1800
   - MongoDB 写入 conversation document（MongoDB TTL 索引 86400s 作为兜底）

2. 每次会话交互时（refine/lookup/compare）：
   - Redis EXPIRE conversation:{id}:state 1800  # 滑动窗口重置
   - MongoDB updated_at 自动刷新（find_one_and_update）

3. 读取会话状态时：
   - 优先从 Redis GET conversation:{id}:state
   - 若 Redis 未命中 → 从 MongoDB 读取 → 回写 Redis（EX 1800）

4. 会话过期时：
   - Redis key 自动过期 → ConversationState 热数据消失
   - MongoDB document 在 86400s 后由 TTL 索引自动清理
   - 两层过期保证：Redis 1800s（精确滑动窗口）+ MongoDB 86400s（硬兜底）
```

**约束**:
- Redis 存储序列化后的 ConversationState（JSON string）
- MongoDB 是 Source of Truth，Redis 是加速层
- Redis 不可用时降级到 MongoDB 直读（不中断服务）