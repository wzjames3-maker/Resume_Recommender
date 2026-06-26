<!-- Module: conversation-memory -->
<!-- Spec Layer: 02 - Data Model -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 数据模型：Conversation Memory（对话记忆模块）

## 模型总览

本模块涉及以下核心模型：

| 模型 | 来源 | 存储位置 | 说明 |
|------|------|----------|------|
| Conversation | 04-domain-model.md Conversation 实体 | MongoDB `conversations` | 对话会话主记录 |
| Message | 04-domain-model.md Message 实体 | MongoDB `messages` | 对话消息 |
| ConversationState | 03-slot-definition.md Conversation Slot | MongoDB（嵌入 Conversation） | 对话上下文状态 |
| SlotMergeResult | 本模块新增 | 内存（不持久化） | Slot 合并操作结果 |

---

## 1. Conversation（对话会话）

直接引用 Domain Model 中的 Conversation 实体定义。

**来源**：04-domain-model.md §9 Conversation

### Schema 定义

```python
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    DELETED = "deleted"


class Conversation(BaseModel):
    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    title: str = ""  # 自动生成: "对话 {YYYY-MM-DD HH:mm}"
    turn_count: int = 0
    status: ConversationStatus = ConversationStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

### MongoDB Document 结构

```json
{
  "_id": "conversation_id (UUID string)",
  "user_id": "user_001",
  "title": "对话 2026-06-23 14:30",
  "turn_count": 5,
  "status": "active",
  "state": {
    "last_query": { "job_title": "Java工程师", "skills": ["Java"], "experience": 5 },
    "last_filters": { "city": "杭州", "education": "985", "gender": "女", "exclude": ["外包"] },
    "last_candidates": [
      { "candidate_id": "resume_001", "candidate_name": "张三", "rank": 1, "score": 92.5 },
      { "candidate_id": "resume_002", "candidate_name": "李四", "rank": 2, "score": 88.3 }
    ],
    "last_sort_by": "score",
    "turn_count": 5,
    "intent_history": ["recruitment.search", "recruitment.refine", "recruitment.refine", "candidate.lookup", "recruitment.refine"]
  },
  "created_at": "2026-06-23T06:30:00Z",
  "updated_at": "2026-06-23T06:35:00Z"
}
```

### 索引

| 索引名 | 字段 | 类型 | 用途 |
|--------|------|------|------|
| `idx_user_id_status` | `user_id` + `status` | 复合索引 | list_conversations 查询 |
| `idx_conversation_id` | `_id` | 主键 | get_conversation 查询 |

---

## 2. Message（对话消息）

直接引用 Domain Model 中的 Message 实体定义。

**来源**：04-domain-model.md §10 Message

### Schema 定义

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any
import uuid


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    role: MessageRole
    content: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    slots: Optional[Dict[str, Any]] = None
    tool_calls: Optional[list] = None
    latency_ms: Optional[int] = None
    tokens: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### MongoDB Document 结构

```json
{
  "_id": "message_id (UUID string)",
  "conversation_id": "conversation_id (UUID string)",
  "role": "user",
  "content": "找5年Java工程师，杭州，985",
  "intent": "recruitment.search",
  "confidence": 0.95,
  "slots": {
    "job_title": "Java工程师",
    "skills": ["Java"],
    "experience": 5,
    "experience_op": ">=",
    "city": "杭州",
    "education": "985"
  },
  "tool_calls": null,
  "latency_ms": 150,
  "tokens": 120,
  "created_at": "2026-06-23T06:30:00Z"
}
```

### 索引

| 索引名 | 字段 | 类型 | 用途 |
|--------|------|------|------|
| `idx_conversation_id_created` | `conversation_id` + `created_at` | 复合索引 | 按对话查询消息（时间正序） |
| `idx_conversation_id` | `conversation_id` | 普通索引 | 按对话删除消息 |

---

## 3. ConversationState（对话上下文状态）

本模块核心状态模型，维护多轮对话的上下文。

**来源**：03-slot-definition.md Conversation Slot

### Schema 定义

```python
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class CandidateRef(BaseModel):
    """last_candidates 中单个候选人的引用信息"""
    candidate_id: str
    candidate_name: str
    rank: int
    score: float


class ConversationState(BaseModel):
    """对话上下文状态，嵌入在 Conversation MongoDB document 中"""
    last_query: Dict[str, Any] = Field(default_factory=dict)
    last_filters: Dict[str, Any] = Field(default_factory=dict)
    last_candidates: List[CandidateRef] = Field(default_factory=list)
    last_sort_by: Optional[str] = None
    turn_count: int = 0
    intent_history: List[str] = Field(default_factory=list)
```

### 字段说明

| 字段 | 类型 | 说明 | 更新时机 |
|------|------|------|----------|
| last_query | dict | 上一次查询的完整 Slots | 每次 search / refine 后 |
| last_filters | dict | 上一次生效的过滤条件 | search 时重置，refine 时合并 |
| last_candidates | list[CandidateRef] | 上一次推荐的候选人列表 | 每次推荐完成后 |
| last_sort_by | str? | 上一次排序方式 | 每次推荐完成后 |
| turn_count | int | 当前对话轮次 | 每次 add_message 后 +1 |
| intent_history | list[str] | 历史意图序列 | 每次 add_message(user) 后追加 |

### last_query 结构示例

```json
{
  "job_title": "Java工程师",
  "skills": ["Java"],
  "experience": 5,
  "experience_op": ">=",
  "city": "杭州",
  "education": "985",
  "gender": "女"
}
```

### last_filters 结构示例

```json
{
  "job_title": "Java工程师",
  "skills": ["Java"],
  "experience": 5,
  "experience_op": ">=",
  "city": "杭州",
  "education": "985",
  "gender": "女",
  "count": 10,
  "sort_by": "score",
  "order": "desc",
  "exclude": ["外包"]
}
```

### last_candidates 结构示例

```json
[
  { "candidate_id": "resume_001", "candidate_name": "张三", "rank": 1, "score": 92.5 },
  { "candidate_id": "resume_002", "candidate_name": "李四", "rank": 2, "score": 88.3 },
  { "candidate_id": "resume_003", "candidate_name": "王五", "rank": 3, "score": 85.1 }
]
```


### Redis 存储结构

```python
# Redis Key 命名规范
conversation:{conversation_id}:state  → JSON string (ConversationState 序列化)
conversation:{conversation_id}:meta   → Hash {user_id, title, turn_count, created_at}

# TTL
EXPIRE conversation:{id}:state 1800   # 30 分钟滑动窗口
EXPIRE conversation:{id}:meta 1800    # 同步 TTL
```

### 读写路径

| 操作 | Redis | MongoDB |
|------|-------|---------|
| 创建会话 | SET state + HMSET meta (EX 1800) | INSERT conversation |
| 读取会话状态 | GET state (优先) | find_one (降级) |
| 更新会话状态 | SET state (EX 1800 重置) | update_one |
| 每次交互 | EXPIRE state 1800 (滑动窗口) | updated_at 刷新 |
| 会话过期 | 自动过期 (1800s) | TTL 索引清理 (86400s) |

---

## 4. SlotMergeResult（Slot 合并结果）

Slot 合并操作的返回值，描述合并类型和影响的字段。

**来源**：本模块新增（基于 03-slot-definition.md 上下文合并规则）

### Schema 定义

```python
from pydantic import BaseModel, Field
from typing import Dict, Any, List
from enum import Enum


class MergeType(str, Enum):
    INCREMENTAL = "增量"    # 新条件追加
    OVERWRITE = "覆盖"      # 同类条件被新值覆盖
    RESET = "重置"          # 新 search 时清空历史


class SearchScope(str, Enum):
    FULL_SEARCH = "full_search"                       # 全库重检
    WITHIN_CANDIDATES = "within_candidates"            # 在 last_candidates 内过滤
    WITHIN_CANDIDATES_FALLBACK = "within_candidates_fallback"  # 先内过滤，为空则全库


class SlotMergeResult(BaseModel):
    """Slot 合并操作结果"""
    merged_slots: Dict[str, Any]          # 合并后的完整 filters
    merge_type: MergeType                  # 本次合并类型
    changed_fields: List[str]              # 本次变更的字段列表
    search_scope: SearchScope              # 建议的检索范围
```

### 合并类型与 search_scope 的映射

| merge_type | changed_fields 包含 | search_scope |
|------------|---------------------|--------------|
| 增量 | 新增的 Candidate Slot | `within_candidates_fallback` |
| 覆盖 | 被覆盖的 Query Slot（count/sort_by 等） | `within_candidates` |
| 增量 + 排除 | exclude 列表 | `within_candidates` |
| 增量 + 核心条件 | job_title / skills | `full_search` |
| 重置 | 全部 | `full_search` |

---

## 5. MongoDB 集合设计

### 5.1 `conversations` 集合

存储 Conversation 主记录和嵌入的 ConversationState。

```javascript
// Collection: conversations
{
  _id: string,           // conversation_id (UUID)
  user_id: string,       // 用户标识
  title: string,         // 会话标题
  turn_count: number,    // 对话轮次
  status: string,        // "active" | "closed" | "deleted"
  state: {               // 嵌入式 ConversationState
    last_query: object,
    last_filters: object,
    last_candidates: array,
    last_sort_by: string | null,
    turn_count: number,
    intent_history: array
  },
  created_at: datetime,
  updated_at: datetime
}
```

**设计决策**：ConversationState 嵌入在 Conversation 中而非独立集合，理由：
1. 一对一关系，无需独立查询 state
2. 读取 state 时只需一次 MongoDB 查询（无 JOIN）
3. 更新 state 和更新 conversation 在同一原子操作中

### 5.2 `messages` 集合

存储所有对话消息。

```javascript
// Collection: messages
{
  _id: string,               // message_id (UUID)
  conversation_id: string,   // 关联会话
  role: string,              // "user" | "assistant" | "system"
  content: string,           // 消息内容
  intent: string | null,     // 识别的意图
  confidence: number | null, // 意图置信度
  slots: object | null,      // 提取的 Slots（快照）
  tool_calls: array | null,  // 工具调用列表
  latency_ms: number | null, // 响应耗时
  tokens: number | null,     // 消耗 Token 数
  created_at: datetime       // 消息时间
}
```

---

## 6. 模型关系图

```
┌─────────────────────────────────────────────┐
│  Conversation (conversations 集合)           │
│                                             │
│  conversation_id  ──────────────┐           │
│  user_id                        │           │
│  title                          │           │
│  turn_count                     │           │
│  status                         │           │
│  ┌───────────────────────────┐  │           │
│  │  ConversationState (嵌入) │  │           │
│  │  last_query               │  │           │
│  │  last_filters             │  │           │
│  │  last_candidates[] ───────┼──┼──────┐    │
│  │  last_sort_by             │  │      │    │
│  │  turn_count               │  │      │    │
│  │  intent_history[]         │  │      │    │
│  └───────────────────────────┘  │      │    │
│  created_at                     │      │    │
│  updated_at                     │      │    │
└─────────────────────────────────┼──────┼────┘
                                  │      │
           ┌──────────────────────┘      │
           │ 1:N                         │ N:1 (引用)
           ▼                             ▼
┌─────────────────────────┐    ┌──────────────────┐
│  Message (messages 集合)  │    │  Resume           │
│                         │    │  (resume-store 模块)│
│  message_id             │    │                    │
│  conversation_id        │    │  candidate_id      │
│  role                   │    │  candidate_name    │
│  content                │    └──────────────────┘
│  intent                 │
│  confidence             │
│  slots                  │
│  created_at             │
└─────────────────────────┘

┌─────────────────────────┐
│  SlotMergeResult         │
│  (内存，不持久化)        │
│                         │
│  merged_slots           │
│  merge_type             │
│  changed_fields         │
│  search_scope           │
└─────────────────────────┘
```

---

## 7. 设计决策

### D-001: ConversationState 嵌入 vs 独立集合

**决策**：嵌入 Conversation document。

**理由**：
1. 一对一关系，state 不可能脱离 conversation 独立存在
2. 减少 MongoDB 查询次数（读取 state 不需要额外 query）
3. 原子更新（conversation + state 在同一 updateOne 中完成）

**权衡**：document 大小上限 16MB。last_candidates 最多 100 条（PRD count 上限），每条约 200 bytes，总计 ~20KB，远低于上限。

### D-002: Message 独立集合 vs 嵌入

**决策**：独立 `messages` 集合。

**理由**：
1. 一对多关系，一个 conversation 可有 100+ messages
2. 嵌入会导致 conversation document 快速膨胀
3. 独立集合支持按 conversation_id + created_at 索引高效分页查询
4. 删除 conversation 时可通过 conversation_id 批量删除 messages

### D-003: last_candidates 存储精简信息

**决策**：last_candidates 只存储 `candidate_id, candidate_name, rank, score`，不存储完整 Resume 数据。

**理由**：
1. 完整 Resume 数据在 resume-store 模块管理
2. last_candidates 仅用于引用定位，详情查询时再去 resume-store 获取
3. 减少 ConversationState 的 document 大小
4. 保持数据单一来源（resume-store 是 Resume 的 Source of Truth）
