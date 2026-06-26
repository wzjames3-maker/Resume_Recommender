<!-- Module: conversation-memory -->
<!-- Spec Layer: 07 - Tech Constraints -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 技术约束：Conversation Memory（对话记忆模块）

## 决策来源

本模块的技术约束来源于 `docs/tech-decision.md`（Phase 3.5 技术选型，已冻结）。

---

## 1. 运行时约束

| 约束 | 值 | 来源 |
|------|-----|------|
| 语言 | Python 3.11+ | tech-decision.md 决策项 1 |
| 运行环境 | Docker 容器内 | AGENTS.md 全局约束 |
| 进程模型 | 单进程（FastAPI + Uvicorn） | tech-decision.md 决策项 2 |

---

## 2. 依赖库版本约束

| 库 | 版本 | 用途 | 来源 |
|----|------|------|------|
| langgraph | >= 0.4 | LangGraph State 定义 | tech-decision.md 决策项 3 |
| langchain-core | >= 0.3 | BaseMessage 基础设施 | tech-decision.md 决策项 3 |
| pymongo | >= 4.9 | MongoDB 持久化 | tech-decision.md Python 依赖清单 |
| pydantic | >= 2.0 | Schema 定义与数据验证 | tech-decision.md 决策项 2 |
| fastapi | >= 0.115 | 内部接口框架 | tech-decision.md 决策项 2 |
| python-json-logger | >= 3.2 | 结构化日志 | tech-decision.md 决策项 14 |

---

## 3. 状态管理约束

### 3.1 LangGraph State

**约束**：ConversationState 必须定义为 LangGraph TypedDict，可直接在 LangGraph StateGraph 中流转。

```python
from typing import TypedDict, List, Optional, Dict, Any
from typing_extensions import Annotated

class ConversationStateDict(TypedDict):
    """LangGraph State 定义，用于 StateGraph 节点间传递"""
    last_query: Dict[str, Any]
    last_filters: Dict[str, Any]
    last_candidates: List[Dict[str, Any]]
    last_sort_by: Optional[str]
    turn_count: int
    intent_history: List[str]
```

**设计约束**：
- LangGraph State 使用 TypedDict 而非 Pydantic BaseModel（LangGraph 要求）
- Pydantic BaseModel 用于 API 层数据验证（add_message / merge_slots 等接口的输入输出）
- 内部 state 流转使用 TypedDict，外部 API 响应使用 Pydantic BaseModel

**双模型映射**：

| 场景 | 使用模型 |
|------|----------|
| LangGraph StateGraph 内部流转 | `ConversationStateDict`（TypedDict） |
| API 接口输入输出 | `ConversationState`（Pydantic BaseModel） |
| MongoDB 序列化/反序列化 | Pydantic `model_dump()` / `model_validate()` |

### 3.2 MongoDB 持久化

**约束**：使用 pymongo >= 4.9（同步驱动），不使用 motor（异步驱动）。

**理由**：
1. tech-decision.md 决策项 6 选择 pymongo，未选择 motor
2. FastAPI 通过 `run_in_executor` 将同步 pymongo 调用包装为异步
3. V1 单机部署，QPS >= 20，同步驱动足够

**包装方式**：

```python
import asyncio
from pymongo import MongoClient

class AsyncConversationStore:
    def __init__(self, mongodb_uri: str):
        self._client = MongoClient(mongodb_uri)
        self._db = self._client["recruitment"]
        self._conversations = self._db["conversations"]
        self._messages = self._db["messages"]
        self._loop = asyncio.get_event_loop()

    async def _run_sync(self, func, *args):
        return await self._loop.run_in_executor(None, func, *args)

    async def create_conversation(self, user_id: str) -> Conversation:
        doc = {...}
        await self._run_sync(self._conversations.insert_one, doc)
        return Conversation(**doc)
```

---

## 4. MongoDB 集合约束

| 约束 | 值 | 说明 |
|------|-----|------|
| 数据库名 | `recruitment` | 与其他模块共用同一数据库 |
| 集合名 | `conversations`, `messages` | 对话主记录和消息分开存储 |
| Document 大小上限 | 16MB | MongoDB 默认限制 |
| 索引策略 | 见 02-data-model.md §5 | user_id + status 复合索引、conversation_id + created_at 复合索引 |

---

## 5. 禁用技术

| 技术 | 禁用原因 | 来源 |
|------|----------|------|
| Redis | V1 单机部署不需要，本地缓存足够 | tech-decision.md 决策项 11 |
| motor (async MongoDB driver) | tech-decision.md 选择 pymongo，不选择 motor | tech-decision.md 决策项 6 |
| 事务（Multi-document Transaction） | 单 document 更新足够，不需要跨集合事务 | 设计决策 |
| 乐观锁（Version 字段） | V1 并发量低，find_one_and_update 原子操作足够 | EC-004 |

---

## 6. 日志约束

### 日志格式

```json
{
    "timestamp": "2026-06-23T06:30:00.000Z",
    "level": "INFO",
    "module": "conversation-memory",
    "action": "add_message",
    "conversation_id": "xxx",
    "user_id": "user_001",
    "intent": "recruitment.search",
    "turn_count": 5,
    "latency_ms": 12
}
```

### 必须记录的事件

| 事件 | 级别 | 说明 |
|------|------|------|
| create_conversation | INFO | 创建新对话 |
| add_message | INFO | 保存消息 |
| merge_slots | INFO | Slot 合并 |
| reset_state | INFO | 状态重置 |
| delete_conversation | INFO | 对话删除 |
| mongodb_fallback | WARNING | MongoDB 不可用，降级到内存 |
| conversation_truncated | WARNING | 对话超长截断 |
| conversation_not_found | WARNING | conversation_id 不存在 |
| mongodb_operation_error | ERROR | MongoDB 操作失败（非连接问题） |

---

## 7. 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `MONGODB_URI` | 是 | `mongodb://localhost:27017` | MongoDB 连接字符串 |
| `MONGODB_DATABASE` | 否 | `recruitment` | 数据库名 |
| `CONVERSATION_MAX_TURNS` | 否 | `50` | 建议新建对话的轮次阈值 |
| `CONVERSATION_TRUNCATE_AT` | 否 | `100` | 截断早期消息的轮次阈值 |
| `LOG_LEVEL` | 否 | `INFO` | 日志级别 |

---

## 8. 性能约束

| 指标 | 目标 | 说明 |
|------|------|------|
| get_state 延迟 | < 10ms | 单次 MongoDB 查询 + 反序列化 |
| add_message 延迟 | < 20ms | 插入 message + 更新 conversation |
| merge_slots 延迟 | < 10ms | 内存计算 + 单次 MongoDB update |
| 持久化写入延迟 | < 30ms | MongoDB 单 document 写入 |
| 并发写入 | 支持 50 并发 | NFR-005: >= 50 并发用户 |

**说明**：本模块不涉及 LLM 调用、Embedding 生成或向量检索，性能瓶颈在 MongoDB 读写。V1 单机部署 + pymongo 同步驱动，上述指标可轻松满足。
