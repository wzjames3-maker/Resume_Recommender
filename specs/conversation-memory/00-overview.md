<!-- Module: conversation-memory -->
<!-- Spec Layer: 00 - Overview -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 模块概览：Conversation Memory（对话记忆模块）

## 1. 模块定位

Conversation Memory 是企业智能招聘 RAG 推荐系统的**多轮对话状态管理模块**，负责维护每个对话会话的上下文状态（Context Memory），包括最近查询条件（last_query）、生效过滤条件（last_filters）、上次推荐候选人（last_candidates）等 Conversation Slot，并实现 Slot 合并逻辑（增量合并 / 条件覆盖 / 条件重置）。它是支撑 `recruitment.refine`（多轮条件修正）和 `candidate.lookup`（候选人查看）的核心基础设施。

## 2. 来源追溯

| 来源 | 内容 |
|------|------|
| PRD FR-006 | 支持多轮对话条件修正（recruitment.refine） |
| PRD FR-007 | 支持 Conversation Memory，维护对话上下文状态 |
| PRD UC-002 | 多轮条件修正（recruitment.refine）— 依赖 Conversation Memory 取出 last_query + last_filters |
| PRD UC-003 | 候选人详情查看（candidate.lookup）— 依赖 last_candidates 定位候选人 |
| PRD UC-004 | 候选人对比（recruitment.compare）— 依赖 last_candidates 获取对比对象 |
| 03-slot-definition.md | Conversation Slot 定义（conversation_id, last_query, last_filters, last_candidates, last_sort_by, turn_count, intent_history） |
| 03-slot-definition.md | 上下文合并规则（增量合并、条件覆盖、条件重置） |
| 04-domain-model.md | Conversation 实体（1:N Message, 1:N Recommendation） |
| 05-business-rules.md | BR-05 Refine 合并规则, BR-06 检索范围决策, BR-07 条件重置 |

## 3. 做什么（In Scope）

| 能力 | 说明 |
|------|------|
| 会话生命周期管理 | 创建 / 获取 / 列出 / 删除 Conversation，管理 conversation_id |
| 消息持久化 | 保存每轮 user + assistant Message（content, intent, slots, confidence） |
| 对话状态维护 | 维护 ConversationState（last_query, last_filters, last_candidates, last_sort_by, turn_count, intent_history） |
| 增量合并 Slots | refine 时追加新条件到 last_filters（如新增 gender=女） |
| 条件覆盖 Slots | 同类条件被新值覆盖（如 count: 10 → 20） |
| 排除条件处理 | 否定表达（"不要外包"）追加到 exclude 列表，不覆盖已有排除项 |
| 条件重置 | 新 search 时清空所有历史 filters，开始全新查询 |
| 检索范围决策 | 根据条件变化类型判断：全库重检 vs last_candidates 内过滤 |
| last_candidates 管理 | 每次推荐后更新候选列表，支持按位置（0-based）或姓名引用 |
| 候选人引用解析 | candidate.lookup 时从 last_candidates 定位目标候选人 |
| MongoDB 持久化 | 对话状态持久化到 MongoDB，支持跨请求恢复 |
| Redis 会话 TTL | 使用 Redis EXPIRE 管理会话过期（30 分钟滑动窗口），MongoDB TTL 作为兜底（24 小时硬过期） |

## 4. 不做什么（Out of Scope）

| 不做 | 说明 | 负责模块 |
|------|------|----------|
| Intent 识别 | 不识别用户输入的意图类型 | intent-router |
| Slot 提取 | 不从自然语言中提取结构化参数 | intent-router |
| 候人检索与排序 | 不执行 Hybrid Retrieval / Metadata Filter / LLM Rerank | recommendation-engine |
| Embedding 生成 | 不调用 BGE-M3 生成查询向量 | vector-index |
| 简历数据查询 | 不直接查询 Resume 实体（仅维护 last_candidates 引用） | resume-store |
| API 认证与鉴权 | 不负责 JWT 和 RBAC | api-layer |
| 前端渲染 | 不处理 UI 展示逻辑 | frontend |
| LLM 调用 | 不调用 LLM 做任何推理 | - |

## 5. 技术栈

| 组件 | 技术选型 | 版本要求 | 用途 |
|------|----------|----------|------|
| 状态管理 | LangGraph State | langgraph >= 0.4 | 定义 ConversationState TypedDict，在 LangGraph Graph 内流转 |
| 持久化 | MongoDB | pymongo >= 4.9 | 对话和消息持久化存储 |
| 数据验证 | Pydantic | Pydantic >= 2.0 | Conversation / Message / ConversationState / SlotMergeResult Schema |
| Web 框架 | FastAPI（内部接口） | FastAPI >= 0.115 | 模块内部服务接口 |
| 日志 | python-json-logger | python-json-logger >= 3.2 | 结构化日志 |
| ID 生成 | uuid4 | Python stdlib | conversation_id / message_id 生成 |
| 会话状态缓存 | Redis | redis >= 5.0 | 会话 TTL 管理、滑动窗口过期、ConversationState 热缓存 |

## 6. 架构位置

```
┌──────────────────────┐
│   Intent Router      │
│   (识别 intent)      │
│                      │
│  ┌────────────────┐  │     ┌──────────────────────────────────────────┐
│  │ Slot Extractor │──┼────>│        Conversation Memory (本模块)       │
│  └────────────────┘  │     │                                          │
└──────────────────────┘     │  ┌──────────────┐  ┌──────────────────┐  │
                             │  │ Conversation │  │ Slot Merge       │  │
                             │  │ Manager      │  │ Engine           │  │
                             │  │ (CRUD)       │  │ (增量/覆盖/重置) │  │
                             │  └──────┬───────┘  └──────┬───────────┘  │
                             │         │                 │              │
                             │  ┌──────▼─────────────────▼───────────┐  │
                             │  │        MongoDB Persistence          │  │
                             │  │  conversations + messages collections│  │
                             │  └────────────────────────────────────┘  │
                             └──────────┬───────────────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
             ┌──────▼──────┐  ┌────────▼────────┐  ┌──────▼──────┐
             │ Recommendation│  │ Intent Router   │  │ API Layer   │
             │ Engine        │  │ (Context-Aware) │  │ (FastAPI)   │
             │ (读取 last_   │  │ (读取 state     │  │             │
             │  candidates)  │  │  做上下文消歧)  │  │             │
             └──────────────┘  └─────────────────┘  └─────────────┘
```

## 7. 数据流

### 7.1 新查询流程（recruitment.search）

```
用户: "找5年Java工程师"
    │
    ▼
Intent Router 识别 → intent=recruitment.search
    │
    ▼
Conversation Memory: reset_state(conversation_id)
    │  → 清空 last_filters, last_candidates
    ▼
Conversation Memory: add_message(role=user, content, intent, slots)
    │
    ▼
Recommendation Engine 执行检索 → 返回 candidates
    │
    ▼
Conversation Memory: update last_query, last_filters, last_candidates, turn_count
    │
    ▼
Conversation Memory: add_message(role=assistant, content, intent, slots)
```

### 7.2 条件修正流程（recruitment.refine）

```
用户: "女生呢"
    │
    ▼
Intent Router 识别 → intent=recruitment.refine, slots={gender: "女"}
    │
    ▼
Conversation Memory: get_state(conversation_id)
    │  → 返回 last_query, last_filters, last_candidates
    ▼
Conversation Memory: merge_slots(conversation_id, new_slots={gender: "女"})
    │  → 增量合并: last_filters = {...旧filters, gender: "女"}
    │  → 返回 SlotMergeResult(merged_slots, merge_type=增量, changed_fields=["gender"])
    ▼
Recommendation Engine 根据 merge_type 决策检索范围
    │  → 仅追加条件 → 先在 last_candidates 内过滤
    ▼
更新 last_candidates, last_query
```

### 7.3 候选人查看流程（candidate.lookup）

```
用户: "第一个人是谁"
    │
    ▼
Intent Router 识别 → intent=candidate.lookup, slots={candidate_ref: "last_candidates[0]"}
    │
    ▼
Conversation Memory: resolve_candidate_ref(conversation_id, "last_candidates[0]")
    │  → 从 last_candidates[0] 取出 {candidate_id, candidate_name}
    ▼
Resume Store: 查询完整简历
```

## 8. 关键约束

1. **引用 Spec 条目** — 所有实现必须追溯到本 Spec 的 REQ/RULE/AC 编号
2. **容器内执行** — 所有测试和运行在 Docker 容器内
3. **原子写入** — 并发写入同一 conversation 时使用 MongoDB `find_one_and_update` 保证原子性
4. **不执行检索** — 本模块仅管理状态，不执行任何检索 / 推荐逻辑
5. **不识别意图** — 本模块不负责 Intent 识别，仅消费 intent-router 的识别结果
6. **状态快照** — 每次 add_message 时将当前 slots 快照写入 Message，保证历史可追溯
7. **50 轮自动分段** — 对话超过 50 轮时建议创建新对话，避免状态膨胀
8. **降级到内存** — MongoDB 不可用时降级到内存状态（不持久化），保证核心链路可用
9. **Redis 优先** — ConversationState 热数据优先读写 Redis，MongoDB 作为持久化归档；Redis 不可用时降级到 MongoDB 直读

## 9. Spec 文件索引

| 文件 | 内容 | 层级 |
|------|------|------|
| `00-overview.md` | 模块概览（本文件） | 概览 |
| `01-requirements.md` | 功能需求列表 | 需求 |
| `02-data-model.md` | 数据模型与 Schema 定义 | 模型 |
| `03-api-contract.md` | 内部接口契约 | 接口 |
| `04-business-rules.md` | 业务规则 | 规则 |
| `05-edge-cases.md` | 边界情况与异常处理 | 边界 |
| `06-acceptance.md` | 验收标准（Given-When-Then） | 验收 |
| `07-tech-constraints.md` | 技术约束与依赖版本 | 约束 |
| `08-dependencies.md` | 模块依赖关系 | 依赖 |
