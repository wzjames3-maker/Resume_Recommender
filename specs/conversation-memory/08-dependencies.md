<!-- Module: conversation-memory -->
<!-- Spec Layer: 08 - Dependencies -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 模块依赖：Conversation Memory（对话记忆模块）

## 依赖总览

```
                    ┌─────────────────────┐
                    │  conversation-memory │
                    │      (本模块)        │
                    └──────────┬──────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │ 前置依赖          │                  │ 后置依赖
            │ (本模块依赖的)    │                  │ (依赖本模块的)
            ▼                  ▼                  ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
    │  MongoDB     │  │  LangGraph   │  │  intent-router   │
    │  (基础设施)   │  │  (状态框架)   │  │  (消费 state)    │
    └──────────────┘  └──────────────┘  └──────────────────┘
                                              │
                                              ▼
                                     ┌──────────────────┐
                                     │  recommendation   │
                                     │  -engine          │
                                     │  (消费 candidates)│
                                     └──────────────────┘
                                              │
                                              ▼
                                     ┌──────────────────┐
                                     │  api-layer        │
                                     │  (消费 CRUD)      │
                                     └──────────────────┘
```

---

## 1. 前置依赖（本模块依赖）

### 1.1 MongoDB（基础设施）

**依赖类型**：基础设施依赖

**依赖内容**：
- MongoDB 实例（Docker 部署）
- pymongo >= 4.9 驱动
- `recruitment` 数据库中的 `conversations` 和 `messages` 集合

**依赖方式**：
- 通过环境变量 `MONGODB_URI` 获取连接字符串
- 本模块自行创建集合和索引（不依赖其他模块初始化）
- MongoDB 不可用时降级到内存存储（EC-007）

**无代码依赖**：本模块不依赖任何其他业务模块的代码。

### 1.2 LangGraph（状态框架）

**依赖类型**：框架依赖

**依赖内容**：
- LangGraph State 定义能力（TypedDict）
- 本模块定义 ConversationStateDict，可在 LangGraph StateGraph 中作为 state 传递

**依赖方式**：
- 导入 `langgraph` 中的 TypedDict 基础设施
- 不依赖 LangGraph 的 Graph / Node / Edge 编排（本模块不定义 Workflow）

**约束**：本模块只定义 State schema，不定义 LangGraph Workflow。Workflow 由 intent-router 模块编排。

### 1.3 Pydantic（数据验证）

**依赖类型**：框架依赖

**依赖内容**：
- Pydantic >= 2.0 BaseModel
- 用于 Conversation / Message / ConversationState / SlotMergeResult 的 Schema 定义

---

## 2. 后置依赖（依赖本模块的模块）

### 2.1 intent-router

**依赖类型**：状态消费

**依赖内容**：

| 接口 | 用途 |
|------|------|
| `get_state(conversation_id)` | 获取对话状态，用于上下文感知的意图识别 |
| `merge_slots(conversation_id, new_slots)` | 合并新 Slots 到对话状态 |
| `reset_state(conversation_id)` | 新 search 时重置对话状态 |
| `add_message(conversation_id, role, content, intent, slots)` | 保存每轮消息 |
| `resolve_candidate_ref(conversation_id, ref)` | 解析候选人引用（candidate.lookup 时） |

**调用时机**：
1. 识别 intent 前 → `get_state` 获取上下文（判断是否 refine 场景）
2. 识别 intent 后 → `add_message` 保存 user 消息
3. recruitment.search → `reset_state` 清空历史
4. recruitment.refine → `merge_slots` 合并条件
5. candidate.lookup → `resolve_candidate_ref` 定位候选人
6. 推荐完成 → `add_message` 保存 assistant 消息

**集成方式**：intent-router 通过 Python 函数调用使用本模块（非 HTTP 接口）。

### 2.2 recommendation-engine

**依赖类型**：状态消费

**依赖内容**：

| 接口 | 用途 |
|------|------|
| `get_last_candidates(conversation_id)` | 获取上次推荐的候选人列表 |
| `update_last_candidates(conversation_id, candidates)` | 推荐完成后更新候选列表 |

**调用时机**：
1. recruitment.refine → `get_last_candidates` 获取上次推荐结果，在内部过滤或作为全库检索的参考
2. 推荐完成 → `update_last_candidates` 更新候选列表

**注意**：recommendation-engine 不直接调用 `merge_slots` 或 `reset_state`，这些操作由 intent-router 负责。

### 2.3 api-layer

**依赖类型**：CRUD 消费

**依赖内容**：

| 接口 | 用途 |
|------|------|
| `create_conversation(user_id)` | API: POST /conversations |
| `get_conversation(conversation_id)` | API: GET /conversations/{id} |
| `list_conversations(user_id, limit, offset)` | API: GET /conversations |
| `delete_conversation(conversation_id)` | API: DELETE /conversations/{id} |

**调用时机**：用户通过 HTTP API 管理对话时。

---

## 3. 无依赖关系的模块

| 模块 | 关系 | 说明 |
|------|------|------|
| resume-parser | 无 | 本模块不涉及简历解析 |
| resume-store | 无直接依赖 | 本模块只存储 candidate_id 引用，不查询 Resume 实体。candidate 详情查询由 api-layer 负责 |
| vector-index | 无 | 本模块不涉及向量操作 |
| frontend | 无 | 本模块是后端内部模块 |

---

## 4. 依赖版本矩阵

| 依赖 | 最低版本 | 推荐版本 | 锁定理由 |
|------|----------|----------|----------|
| Python | 3.11 | 3.11 | tech-decision.md |
| langgraph | 0.4.0 | 最新 stable | tech-decision.md: "版本迭代快，API 可能变化" |
| langchain-core | 0.3.0 | 最新 stable | 与 langgraph 版本配套 |
| pymongo | 4.9.0 | 最新 stable | tech-decision.md |
| pydantic | 2.0.0 | 最新 stable | tech-decision.md |
| fastapi | 0.115.0 | 最新 stable | tech-decision.md |
| python-json-logger | 3.2.0 | 最新 stable | tech-decision.md |

---

## 5. 初始化依赖顺序

```
1. MongoDB 连接初始化（基础设施层）
2. ConversationStore 初始化（本模块核心类）
   - 创建 conversations 集合索引
   - 创建 messages 集合索引
3. intent-router 初始化（消费本模块）
4. recommendation-engine 初始化（消费本模块）
5. api-layer 初始化（消费本模块）
```

**约束**：本模块必须在 intent-router 和 recommendation-engine 之前初始化（它们依赖本模块提供的接口）。

---

## 6. 部署依赖

### Docker Compose 依赖

```yaml
services:
  mongodb:           # 前置：MongoDB 必须先启动
    image: mongo:7
    ports:
      - "27017:27017"

  # conversation-memory 不是独立服务
  # 它是 FastAPI 应用内部的模块
  # 通过 import 使用，不通过 HTTP 调用

  api:
    depends_on:
      - mongodb      # 依赖 MongoDB
    environment:
      - MONGODB_URI=mongodb://mongodb:27017
```

**关键约束**：conversation-memory 是 Python 模块（不是独立微服务），通过 `import` 使用，不通过 HTTP/gRPC 调用。

---

## 7. 依赖风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| MongoDB 不可用 | 对话状态无法持久化 | EC-007: 降级到内存存储 |
| pymongo 版本不兼容 | 连接/查询失败 | 锁定 pymongo >= 4.9 |
| LangGraph API 变化 | State 定义方式变化 | 核心逻辑封装在自定义类中，降低对 LangGraph API 的直接依赖（tech-decision.md 风险缓解） |
| MongoDB document 膨胀 | last_candidates 过大 | RULE-008: 50 轮警告 + 100 轮截断；last_candidates 最多 100 条 |
