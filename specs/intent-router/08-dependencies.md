<!-- Module: intent-router -->
<!-- Spec Layer: 08 - Dependencies -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 模块依赖：Intent Router（意图路由模块）

## 依赖总览

```
                  ┌─────────────────────┐
                  │   Intent Router     │
                  │   (本模块)           │
                  └──────┬──────┬───────┘
                         │      │
              ┌──────────┘      └──────────┐
              ▼                             ▼
   ┌──────────────────┐          ┌──────────────────┐
   │   前置依赖        │          │   后置依赖        │
   │   (本模块依赖)    │          │   (依赖本模块)    │
   └──────────────────┘          └──────────────────┘
```

---

## 一、前置依赖（本模块依赖的模块/服务）

### DEP-001: Conversation Memory（对话记忆）

| 属性 | 值 |
|------|-----|
| 依赖类型 | 运行时依赖（强依赖） |
| 模块 | `conversation-memory` |
| 接口 | `get_context(conversation_id: str) -> ConversationContext` |
| 数据 | last_query, last_filters, last_candidates, turn_count, intent_history |
| 影响范围 | REQ-003（上下文感知）, RULE-003~RULE-014（多轮对话规则） |

**依赖说明**：
- Intent Router 在 `fetch_context` 节点调用 Conversation Memory 获取上下文
- 无上下文时按首轮对话处理（EC-012）
- Conversation Memory 不可用时降级为空上下文，不阻塞主流程

**接口契约**：

```python
# conversation-memory 模块提供的接口
async def get_context(conversation_id: str) -> ConversationContext | None:
    """
    获取指定会话的对话上下文。

    返回 None 的情况:
    - conversation_id 不存在
    - 会话已过期（超过 TTL）
    - 首轮对话（无历史）
    """
```

**失败处理**：

```
IF Conversation Memory 不可用:
    context = ConversationContext(
        conversation_id=conversation_id,
        turn_count=0,
        last_query=None,
        last_filters=None,
        last_candidates=None,
        last_intent=None,
        intent_history=[]
    )
    → 按首轮对话处理
    → Audit Log 记录 warning="context_fetch_failed"
```

---

### DEP-002: LLM API（大语言模型服务）

| 属性 | 值 |
|------|-----|
| 依赖类型 | 运行时依赖（强依赖，有降级） |
| 服务 | DeepSeek API（主）, OpenAI API（备） |
| 协议 | OpenAI Compatible API |
| 影响范围 | 全部意图识别和 Slot 提取 |

**依赖说明**：
- Intent Router 的核心功能完全依赖 LLM
- DeepSeek 不可用时降级到 OpenAI（RULE-017）
- 双 LLM 均不可用时返回 Fallback（EC-008）

**API 端点**：

| LLM | Base URL | 模型 | 用途 |
|-----|----------|------|------|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` | 主力意图识别 |
| OpenAI | `https://api.openai.com` | `gpt-4o-mini` | 备用降级 |

---

### DEP-003: 配置服务

| 属性 | 值 |
|------|-----|
| 依赖类型 | 启动时依赖（弱依赖） |
| 来源 | `config.yaml` + 环境变量 |
| 影响范围 | 置信度阈值、LLM 配置、超时设置等 |

**依赖说明**：
- 配置文件在模块启动时加载
- 配置缺失时使用默认值
- API Key 从环境变量读取

**关键配置项**：

| 配置项 | 环境变量 | 默认值 |
|--------|----------|--------|
| DeepSeek API Key | `DEEPSEEK_API_KEY` | 无（必填） |
| OpenAI API Key | `OPENAI_API_KEY` | 无（备用，可选） |
| 置信度阈值 | `INTENT_CONFIDENCE_THRESHOLD` | 0.6 |
| LLM 超时 | `INTENT_LLM_TIMEOUT` | 10 |

---

## 二、后置依赖（依赖本模块的模块/服务）

### DEP-004: Recommendation Engine（推荐引擎）

| 属性 | 值 |
|------|-----|
| 依赖类型 | 被依赖（下游消费者） |
| 模块 | `recommendation-engine` |
| 消费的 Intent | `recruitment.search`, `recruitment.refine`, `recruitment.compare` |
| 消费的数据 | `IntentResult`（intent + merged_slots + query_slots） |

**数据流**：

```
Intent Router ──(IntentResult)──> Recommendation Engine
                                   ├── Hybrid Retrieval
                                   ├── Metadata Filter
                                   └── LLM Rerank
```

**接口约定**：
- Intent Router 通过 LangGraph Conditional Edge 将 `recruitment.search` 路由到 `hybrid_search_workflow`
- Recommendation Engine 接收 `IntentRouterState` 中的 `intent_result` 和 `merged_slots`
- Intent Router 不对 Recommendation Engine 的内部逻辑有任何假设

---

### DEP-005: Resume Store（简历存储）

| 属性 | 值 |
|------|-----|
| 依赖类型 | 被依赖（下游消费者） |
| 模块 | `resume-store` |
| 消费的 Intent | `resume.upload`, `resume.manage`, `candidate.lookup` |
| 消费的数据 | `IntentResult`（intent + candidate_slots） |

**数据流**：

```
Intent Router ──(IntentResult)──> Resume Store
                                   ├── Resume Upload（resume.upload）
                                   ├── Resume Manage（resume.manage）
                                   └── Candidate Lookup（candidate.lookup）
```

**接口约定**：
- `resume.upload` 路由到 `upload_workflow`，由 Resume Parser + Resume Store 处理
- `resume.manage` 路由到 `manage_workflow`，由 Resume Store 处理
- `candidate.lookup` 路由到 `lookup_workflow`，由 Resume Store 查询候选人详情

---

### DEP-006: Knowledge RAG（知识问答）

| 属性 | 值 |
|------|-----|
| 依赖类型 | 被依赖（下游消费者） |
| 模块 | `knowledge-rag`（V2 实现，V1 占位） |
| 消费的 Intent | `knowledge.qa` |
| 消费的数据 | `IntentResult`（intent + raw_query） |

**说明**：PRD 将 knowledge.qa 标记为 P2 优先级，V1 中 `qa_workflow` 节点可返回 "该功能即将上线" 的占位回复。

---

### DEP-007: Analytics（数据分析）

| 属性 | 值 |
|------|-----|
| 依赖类型 | 被依赖（下游消费者） |
| 模块 | `analytics`（V2 实现，V1 占位） |
| 消费的 Intent | `analytics` |
| 消费的数据 | `IntentResult`（intent + candidate_slots） |

**说明**：PRD 将 analytics 标记为 P2 优先级，V1 中 `analytics_workflow` 节点可返回 "该功能即将上线" 的占位回复。

---

### DEP-008: API Layer（API 层）

| 属性 | 值 |
|------|-----|
| 依赖类型 | 被依赖（上游调用方） |
| 模块 | `api-layer` |
| 调用方式 | 通过 LangGraph Graph 的 `ainvoke()` / `astream()` 调用 |

**数据流**：

```
API Layer ──(query, conversation_id)──> Intent Router (LangGraph Graph)
API Layer <──(IntentRouterState)─────── Intent Router
```

**接口约定**：
- API Layer 负责 JWT 认证和用户身份识别
- API Layer 将 `query` 和 `conversation_id` 传入 Intent Router
- API Layer 从 `IntentRouterState` 中获取路由结果并转发到对应 Workflow
- API Layer 负责 PII 脱敏（Intent Router 不做 PII 处理）

---

## 三、依赖关系图

```
┌──────────────┐
│  API Layer   │ ← 上游调用方
│  (FastAPI)   │
└──────┬───────┘
       │ ainvoke(astream)
       ▼
┌──────────────────────────────────────────────┐
│            Intent Router (本模块)              │
│                                              │
│  fetch_context ──> classify_intent ──> ...   │
└──┬──────────┬──────────────┬─────────────────┘
   │          │              │
   ▼          ▼              ▼
┌────────┐ ┌──────┐ ┌────────────────┐
│Convers.│ │ LLM  │ │  Config        │
│Memory  │ │ API  │ │  (yaml + env)  │
│(前置)   │ │(前置) │ │  (前置)        │
└────────┘ └──────┘ └────────────────┘

       │ 路由分发
       ▼
┌──────────────┬──────────────┬──────────────┐
│ Recommendation│ Resume Store │ Knowledge    │
│ Engine (后置)  │ (后置)       │ RAG (后置)   │
└──────────────┴──────────────┴──────────────┘
```

---

## 四、依赖版本锁定

```txt
# requirements.txt 中 Intent Router 相关的依赖

# Agent 编排
langgraph>=0.4,<1.0
langchain-core>=0.3,<1.0
langchain-openai>=0.3,<1.0

# 数据验证
pydantic>=2.0,<3.0

# HTTP 客户端
httpx>=0.28,<1.0

# 日志
python-json-logger>=3.2,<4.0

# 测试
pytest>=8.0
pytest-asyncio>=0.24
```

**版本锁定策略**：
- 主版本号锁定（防止破坏性更新）
- 次版本号允许升级（获取 bug 修复和新功能）
- LangGraph 版本迭代快，需关注 changelog（tech-decision.md 风险项）

---

## 五、依赖风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| DeepSeek API 不可用 | 意图识别完全失效 | 低 | OpenAI 备用 LLM（RULE-017） |
| Conversation Memory 不可用 | 多轮对话失效 | 低 | 降级为单轮模式（EC-012） |
| LangGraph 版本破坏性更新 | 编译失败 | 中 | 锁定主版本号；核心逻辑封装在自定义 Node 中 |
| LLM 输出格式不稳定 | Pydantic 校验失败 | 低 | Structured Output 约束 + Fallback 降级 |
| LLM Token 成本超预期 | 运营成本增加 | 中 | 控制 System Prompt 长度；温度设为 0 减少无效输出 |
