<!-- Module: intent-router -->
<!-- Spec Layer: 00 - Overview -->
<!-- 变更: Tier L - RAG 全量重构 (引入 LangGraph StateGraph) -->
<!-- Date: 2026-07-03 -->

# 模块概览：Intent Router（意图路由模块）

## 1. 模块定位

Intent Router 是企业智能招聘 RAG 推荐系统的**请求入口与调度中枢模块**，基于 LangGraph StateGraph 实现有状态的多轮对话编排。负责识别用户意图（Intent）、提取结构化参数（Slots），通过 Conditional Edge 将请求路由到对应的下游 Workflow。

## 2. 来源追溯

| 来源 | 内容 |
|------|------|
| PRD FR-001 | 支持自然语言意图识别（10 类 Intent） |
| PRD FR-006 | 支持多轮对话上下文管理 |
| PRD FR-007 | 支持条件修正（recruitment.refine 增量合并） |
| tech-decision.md §3 | LangGraph StateGraph + Tool Calling + Conditional Edge |

## 3. 做什么（In Scope）

| 能力 | 说明 |
|------|------|
| LangGraph StateGraph | 使用 StateGraph 管理对话状态，替代旧 if/elif 路由 |
| Intent 识别 | LLM + few-shot prompt 识别 10 类 Intent，输出 confidence |
| Slot 提取 | 从用户输入提取 Candidate Slot + Query Slot |
| Conditional Edge | 根据 Intent 类型通过 LangGraph conditional edge 分发到 Workflow Node |
| 上下文感知 | 集成 Conversation Memory，支持多轮消歧和 Slot 合并 |
| Checkpoint | LangGraph MemorySaver 支持对话回溯和重放 |
| Fallback | 置信度不足或未匹配 Intent 时返回引导性回复 |

## 4. 不做什么（Out of Scope）

| 不做 | 负责模块 |
|------|----------|
| 候选人检索与排序 | recommendation-engine |
| 简历解析与入库 | resume-parser |
| 简历 CRUD 操作 | resume-store |
| 向量索引管理 | vector-index |
| 对话历史持久化 | conversation-memory |
| Embedding 生成 | vector-index |
| 前端渲染 | frontend |

## 5. LangGraph StateGraph 设计

```
StateGraph(AgentState)
  │
  ├── entry_point: intent_classifier
  │
  ├── Node: intent_classifier
  │     LLM + few-shot prompt → IntentResult(intent, confidence, raw_slots)
  │     └── conditional_edge: route_by_intent
  │         ├── search  → slot_extractor
  │         ├── refine  → slot_extractor
  │         ├── lookup  → candidate_lookup_handler
  │         ├── compare → compare_handler
  │         ├── upload  → upload_handler
  │         ├── manage  → manage_handler
  │         ├── qa      → qa_handler
  │         ├── analytics → analytics_handler
  │         └── fallback → fallback
  │
  ├── Node: slot_extractor
  │     合并 conversation context + 新 slots（增量合并）
  │     └── edge → hybrid_search (ToolNode → recommendation-engine)
  │
  ├── Node: hybrid_search (ToolNode)
  │     调用 recommendation-engine.hybrid_retrieve()
  │     └── edge → reranker (ToolNode → recommendation-engine)
  │
  ├── Node: reranker (ToolNode)
  │     调用 recommendation-engine.rerank()
  │     └── edge → context_builder
  │
  ├── Node: context_builder
  │     构建 LLM 上下文（候选人 + 匹配内容 + 招聘需求）
  │     └── edge → reason_generator
  │
  ├── Node: reason_generator
  │     LLM 生成推荐理由 + score_breakdown
  │     └── edge → END
  │
  │   ── 非搜索型 Intent 节点 ──
  │
  ├── Node: candidate_lookup_handler
  │     通过 resume-store 查询候选人详情
  │     └── edge → END
  │
  ├── Node: compare_handler
  │     对比多个候选人（调用 recommendation-engine.compare）
  │     └── edge → END
  │
  ├── Node: upload_handler
  │     代理到 resume-parser + resume-store + vector-index 入库流程
  │     └── edge → END
  │
  ├── Node: manage_handler
  │     代理到 resume-store 的 CRUD 操作
  │     └── edge → END
  │
  ├── Node: qa_handler
  │     调用 knowledge-base RAG QA 流程
  │     └── edge → END
  │
  ├── Node: analytics_handler
  │     查询统计数据
  │     └── edge → END
  │
  └── Node: fallback
        返回引导性回复（提示可用的操作类型）
        └── edge → END
```

### AgentState 定义

```python
class AgentState(TypedDict):
    messages: list             # 对话消息历史
    intent: IntentEnum | None
    slots: CandidateSlot | None
    raw_query: str
    conversation_id: str | None
    retrieval_results: list[RetrievalResult]
    candidates: list[dict]
    degradation: dict | None
    error: str | None
```

### 路由规则

| Intent | Route | 说明 |
|--------|-------|------|
| `recruitment.search` | slot_extractor → search pipeline | 完整检索→重排→理由链路 |
| `recruitment.refine` | slot_extractor → search pipeline | 增量合并 Slots 后走相同链路 |
| `candidate.lookup` | candidate_lookup_handler | 查 resume-store 返回候选人详情 |
| `recruitment.compare` | compare_handler | 多候选人对比 |
| `resume.upload` | upload_handler | 文件上传→解析→入库 |
| `resume.manage` | manage_handler | 简历列表/删除/状态变更 |
| `knowledge.qa` | qa_handler | 知识库 RAG 问答 |
| `analytics` | analytics_handler | 统计查询 |
| `chat` / 未匹配 | fallback | 引导性回复 |

## 6. 技术栈

| 组件 | 版本 | 用途 |
|------|------|------|
| langgraph | >=0.2 | StateGraph + MemorySaver + ToolNode |
| langchain-core | >=0.3 | BaseMessage, StructuredOutput |
| langchain-openai | >=0.3 | OpenAI Compatible API 调用 |
| LLM 主模型 | DeepSeek deepseek-chat | Intent 识别 + Slot 提取 |
| LLM 备用模型 | OpenAI gpt-4o-mini | DeepSeek 不可用时降级 |
| Pydantic | >=2.0 | Intent/Slot Schema 定义与校验 |
| Redis | >=5.0 | 意图识别结果缓存（相同 query 跳过 LLM） |

## 7. 数据流

```
用户输入 (query: str)
    │
    ▼
┌──────────────────┐     ┌───────────────────┐
│ Conversation     │────>│ Context Assembly   │
│ Memory 查询      │     │ (组装上下文 prompt) │
└──────────────────┘     └────────┬──────────┘
                                  │
                                  ▼
                        ┌───────────────────┐
                        │ intent_classifier  │
                        │ (LLM + few-shot    │
                        │  prompt)           │
                        └────────┬──────────┘
                                 │
                          ┌──────▼──────┐
                          │ Confidence  │
                          │ >= 0.6 ?    │
                          └──┬──────┬───┘
                        Yes  │      │ No
                             ▼      ▼
                    ┌──────────┐  ┌──────────┐
                    │ Route to │  │ Fallback │
                    │ Node     │  │ Response │
                    └────┬─────┘  └──────────┘
                         │
              ┌──────────┼──────────┬────────────┐
              ▼          ▼         ▼            ▼
         search/     lookup/    upload/       qa/
         refine      compare    manage        analytics
              │          │         │            │
              ▼          ▼         ▼            ▼
         slot_extractor │    resume-parser   knowledge-base
              │          │    resume-store    RAG QA
              ▼          ▼    vector-index
         hybrid_search  resume-store
         reranker
         context_builder
         reason_generator
              │
              ▼
         Final Output
```

## 8. 关键约束

1. **StateGraph 编排** — 路由由 LangGraph conditional edge 执行，禁用 if/elif 硬编码
2. **上下文感知** — 有对话历史时必须优先考虑 recruitment.refine（增量合并 Slots）
3. **置信度门控** — confidence < 0.6 必须触发 Fallback
4. **Slot 覆盖规则** — 同类 Slot 新值覆盖旧值，不同类 Slot 增量合并
5. **审计完整** — 100% 的意图识别结果写入 Audit Log
6. **LLM 降级** — DeepSeek 不可用时自动降级到 OpenAI 备用模型
7. **意图识别缓存** — 相同查询（MD5 hash）缓存到 Redis，TTL 1h

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
