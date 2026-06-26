<!-- Module: intent-router -->
<!-- Spec Layer: 00 - Overview -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 模块概览：Intent Router（意图路由模块）

## 1. 模块定位

Intent Router 是企业智能招聘 RAG 推荐系统的**请求入口与调度中枢模块**，负责识别用户自然语言输入的意图（Intent）、提取结构化参数（Slots），并将请求路由到对应的下游 Workflow 执行。它是连接用户输入与后端业务逻辑的核心桥梁。

## 2. 来源追溯

| 来源 | 内容 |
|------|------|
| PRD FR-001 | 支持自然语言意图识别（10 类 Intent） |
| PRD FR-006 | 支持多轮对话上下文管理（Conversation Memory 集成） |
| PRD FR-007 | 支持条件修正（recruitment.refine 增量合并） |
| PRD UC-001 | 智能候选人检索（recruitment.search） |
| PRD UC-002 | 多轮条件修正（recruitment.refine） |
| PRD UC-003 | 候选人详情查看（candidate.lookup） |
| PRD UC-004 | 候选人对比（recruitment.compare） |
| PRD UC-005 | 简历上传入库（resume.upload） |
| PRD UC-006 | 简历管理（resume.manage） |
| PRD UC-007 | 知识问答（knowledge.qa） |
| PRD UC-008 | 数据统计（analytics） |
| 02-intent-inventory.md | 10 类 Intent 定义 + 优先级 + 触发 Workflow |
| 03-slot-definition.md | 3 类 Slot 定义（Candidate/Query/Conversation） |
| 05-business-rules.md | BR-05~BR-07 多轮对话规则，BR-14~BR-15 候选人操作规则，BR-17 Fallback 规则 |

## 3. 做什么（In Scope）

| 能力 | 说明 |
|------|------|
| Intent 识别 | 使用 LLM Function Calling + Pydantic Structured Output 识别 10 类 Intent |
| 置信度评估 | 每次识别输出 confidence 分数，低于阈值（0.6）触发 Fallback |
| Slot 提取 | 从用户输入中提取 Candidate Slot（17 个字段）和 Query Slot（5 个字段） |
| 上下文感知 | 集成 Conversation Memory，支持多轮对话场景下的意图消歧和 Slot 增量合并 |
| Intent 路由分发 | 通过 LangGraph Conditional Edge 将请求分发到对应的下游 Workflow |
| 排除条件解析 | 识别"不要XX"等否定表达，转换为 exclude_slot |
| Audit Log 写入 | 每次意图识别结果写入 Audit Log（Query/Intent/Slots/Confidence/Latency） |
| Fallback 引导 | 置信度不足时返回引导性回复，不静默失败 |

## 4. 不做什么（Out of Scope）

| 不做 | 说明 | 负责模块 |
|------|------|----------|
| 候选人检索与排序 | 不执行 Hybrid Retrieval / Metadata Filter / LLM Rerank | recommendation-engine |
| 简历解析与入库 | 不解析简历文件 | resume-parser |
| 简历 CRUD 操作 | 不执行简历的增删改查 | resume-store |
| 向量索引管理 | 不管理 Milvus 中的向量数据 | vector-index |
| 对话历史持久化 | 不负责对话历史的存储和检索 | conversation-memory |
| LLM Rerank | 不对推荐结果重排序 | recommendation-engine |
| Embedding 生成 | 不调用 BGE-M3 生成向量 | vector-index |
| 前端渲染 | 不处理 UI 展示逻辑 | frontend |

## 5. 技术栈

| 组件 | 技术选型 | 版本要求 | 用途 |
|------|----------|----------|------|
| Agent 编排 | LangGraph StateGraph | langgraph >= 0.4 | 定义 Intent Router 的节点和边，状态管理 |
| LangChain 核心 | langchain-core | langchain-core >= 0.3 | BaseMessage、StructuredOutput 基础设施 |
| LLM 调用 | langchain-openai | langchain-openai >= 0.3 | DeepSeek/OpenAI API 调用（OpenAI Compatible） |
| LLM 主模型 | DeepSeek | deepseek-chat | Intent 识别 + Slot 提取的主 LLM |
| LLM 备用模型 | OpenAI | gpt-4o-mini | DeepSeek 不可用时的降级 LLM |
| 数据验证 | Pydantic | Pydantic >= 2.0 | Intent/Slot 的 Schema 定义、LLM 输出约束 |
| Web 框架 | FastAPI（内部接口） | FastAPI >= 0.115 | 模块内部服务接口 |
| 日志 | python-json-logger | python-json-logger >= 3.2 | 结构化 Audit Log |
| 缓存 | Redis | redis >= 5.0 | 意图识别结果缓存（高频查询跳过 LLM） |

## 6. 架构位置

```
┌──────────────┐     ┌─────────────────────────────────────────────────┐
│   HR 输入     │────>│              Intent Router (本模块)              │
│  自然语言     │     │                                                 │
└──────────────┘     │  ┌─────────────┐    ┌──────────────┐           │
                     │  │ Intent      │    │ Slot         │           │
         ┌───────────│  │ Classifier  │    │ Extractor    │           │
         │           │  │ (LLM FC)    │    │ (LLM FC)     │           │
         │           │  └──────┬──────┘    └──────┬───────┘           │
         │           │         │                  │                    │
         │           │  ┌──────▼──────────────────▼───────┐           │
         │           │  │         LangGraph StateGraph     │           │
         │           │  │  (Conditional Edge Router)       │           │
         │           │  └──────┬──────┬──────┬──────┬─────┘           │
         │           └─────────┼──────┼──────┼──────┼─────────────────┘
         │                     │      │      │      │
         │            ┌────────▼┐ ┌───▼───┐ ┌▼────┐ ┌▼──────────┐
         │            │Hybrid   │ │Resume │ │RAG  │ │Chat       │
         │            │Search   │ │Parser │ │QA   │ │Response   │
         │            └─────────┘ └───────┘ └─────┘ └───────────┘
         │
         │           ┌──────────────────┐
         └──────────>│ Conversation     │
                     │ Memory           │
                     │ (上下文提供者)    │
                     └──────────────────┘
```

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
                        │ LLM Function Call  │
                        │ (Intent + Slots    │
                        │  同时提取)         │
                        └────────┬──────────┘
                                 │
                                 ▼
                        ┌───────────────────┐
                        │ Pydantic 校验      │
                        │ (IntentResult)     │
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
                    │ Workflow │  │ Response │
                    └──────────┘  └──────────┘
```

## 8. 关键约束

1. **LLM Function Calling 驱动** — Intent 识别和 Slot 提取必须通过 LLM Structured Output + Pydantic Schema 实现，禁用 regex 分类
2. **上下文感知** — 有对话历史时必须优先考虑 recruitment.refine（BR-03）
3. **置信度门控** — confidence < 0.6 必须触发 Fallback，不可跳过（BR-02/BR-17）
4. **意图优先级** — 多意图冲突时按 10 级优先级表判定（resume.upload 最高，fallback 最低）
5. **Slot 覆盖规则** — 同类 Slot 新值覆盖旧值，不同类 Slot 增量合并（BR-05）
6. **审计完整** — 100% 的意图识别结果必须写入 Audit Log
7. **容器内执行** — 所有测试和运行在 Docker 容器内
8. **LLM 降级** — DeepSeek 不可用时自动降级到 OpenAI 备用模型
9. **意图识别缓存** — 相同查询文本（MD5 hash）的 Intent 识别结果缓存到 Redis，TTL 1 小时，跳过 LLM Function Calling 调用

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
