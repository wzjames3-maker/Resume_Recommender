<!-- Module: intent-router -->
<!-- Spec Layer: 07 - Tech Constraints -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 技术约束：Intent Router（意图路由模块）

## 来源

本文件的技术决策依据 `docs/tech-decision.md`（冻结版），所有约束均基于已冻结的技术选型。

---

## 1. 语言与运行时

| 约束 | 值 | 来源 |
|------|-----|------|
| 编程语言 | Python 3.11+ | tech-decision.md 决策项 1 |
| 运行环境 | Docker 容器 | tech-decision.md 决策项 12 |

---

## 2. 核心依赖版本

| 依赖 | 最低版本 | 用途 | 来源 |
|------|----------|------|------|
| `langgraph` | >= 0.4 | Agent 编排，StateGraph + Conditional Edge | tech-decision.md 决策项 3 |
| `langchain-core` | >= 0.3 | BaseMessage、StructuredOutput 基础设施 | tech-decision.md 决策项 3 |
| `langchain-openai` | >= 0.3 | DeepSeek/OpenAI API 调用（OpenAI Compatible） | tech-decision.md 决策项 3 |
| `pydantic` | >= 2.0 | Schema 定义、LLM 输出约束、数据验证 | tech-decision.md 决策项 2 |
| `fastapi` | >= 0.115 | 内部服务接口（如需独立部署） | tech-decision.md 决策项 2 |
| `python-json-logger` | >= 3.2 | 结构化 Audit Log | tech-decision.md 决策项 14 |
| `httpx` | >= 0.28 | HTTP 客户端（LLM API 调用） | tech-decision.md |

---

## 3. LLM 约束

### 主 LLM：DeepSeek

| 约束 | 值 | 说明 |
|------|-----|------|
| 模型 | `deepseek-chat` | 主力意图识别模型 |
| API 协议 | OpenAI Compatible | 使用 `langchain-openai` 的 `ChatOpenAI` 类 |
| Base URL | `https://api.deepseek.com` | DeepSeek API 端点 |
| Function Calling | 支持 | 通过 `with_structured_output()` 使用 |
| 上下文窗口 | 128K tokens | 足够包含对话历史 + System Prompt |
| 超时设置 | 10 秒 | 单次调用超时 |

### 备用 LLM：OpenAI

| 约束 | 值 | 说明 |
|------|-----|------|
| 模型 | `gpt-4o-mini` | 降级时使用的备用模型 |
| API 协议 | 原生 OpenAI | `api.openai.com` |
| Function Calling | 支持 | 与 DeepSeek 兼容 |
| 超时设置 | 10 秒 | 单次调用超时 |

### LLM 使用方式

```python
from langchain_openai import ChatOpenAI

# 主 LLM（DeepSeek）
primary_llm = ChatOpenAI(
    model="deepseek-chat",
    base_url="https://api.deepseek.com",
    api_key=settings.DEEPSEEK_API_KEY,
    timeout=10,
    temperature=0,  # 意图识别需要确定性输出
)

# 备用 LLM（OpenAI）
backup_llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=settings.OPENAI_API_KEY,
    timeout=10,
    temperature=0,
)

# Structured Output
structured_llm = primary_llm.with_structured_output(IntentClassificationOutput)
```

---

## 4. LangGraph 约束

### StateGraph 定义

```python
from langgraph.graph import StateGraph, END

graph = StateGraph(IntentRouterState)

# 节点
graph.add_node("fetch_context", fetch_context_node)
graph.add_node("classify_intent", classify_intent_node)
graph.add_node("validate_result", validate_result_node)
graph.add_node("merge_slots", merge_slots_node)
graph.add_node("fallback_handler", fallback_handler_node)
graph.add_node("write_audit_log", write_audit_log_node)

# 边
graph.set_entry_point("fetch_context")
graph.add_edge("fetch_context", "classify_intent")
graph.add_edge("classify_intent", "validate_result")
graph.add_conditional_edges(
    "validate_result",
    confidence_check,  # 根据 confidence 路由
    {
        "pass": "merge_slots",
        "fail": "fallback_handler",
    },
)
graph.add_edge("merge_slots", "write_audit_log")
graph.add_edge("fallback_handler", "write_audit_log")
graph.add_conditional_edges(
    "write_audit_log",
    route_intent,  # 根据 intent 路由到 Workflow
    ROUTE_MAP,
)
```

### Conditional Edge 约束

- 路由函数必须是纯函数（无副作用）
- 路由决策基于 `state["intent_result"].intent`
- 路由映射表 `ROUTE_MAP` 必须覆盖全部 10 类 Intent

---

## 5. Pydantic 约束

| 约束 | 说明 |
|------|------|
| 版本 | Pydantic >= 2.0（使用 V2 API） |
| LLM 输出约束 | 必须使用 `with_structured_output()` 而非手动 JSON 解析 |
| 模型配置 | 使用 `model_config = ConfigDict(use_enum_values=True)` |
| 校验模式 | `model_validate()` 用于校验 LLM 输出 |
| 序列化 | `model_dump()` 用于序列化到 Audit Log |

---

## 6. 禁用技术

| 禁用项 | 原因 | 替代方案 |
|--------|------|----------|
| regex 做 Intent 分类 | 准确率低（~60%），无法处理语义模糊 | LLM Function Calling |
| 关键词列表做 Slot 提取 | 无法处理复合表达和上下文 | LLM Structured Output |
| spaCy / NLP 库做实体提取 | 增加依赖复杂度，LLM 已覆盖此能力 | LLM 原生能力 |
| 本地 LLM（Ollama 等） | V1 不做本地部署 | 云端 API（DeepSeek/OpenAI） |

---

## 7. 性能约束

| 指标 | 目标 | 说明 |
|------|------|------|
| classify_intent 延迟 | P95 <= 800ms | 单次 LLM 调用 |
| 含重试延迟 | P99 <= 1500ms | 含 1 次重试 |
| 端到端（Intent Router） | P95 <= 1s | 含上下文获取 + 路由 |
| LLM Token 消耗 | 单次 <= 1000 tokens | System Prompt + Context + Query |
| 并发处理 | >= 50 并发 | 异步调用，无阻塞 |

---

## 8. 配置约束

所有可调参数通过配置文件管理，不硬编码在代码中。

```yaml
# config.yaml
intent:
  confidence_threshold: 0.6      # 置信度阈值
  llm_timeout_seconds: 10        # LLM 调用超时
  max_input_length: 2000         # 最大输入长度
  max_retries: 1                 # 最大重试次数
  refine_count_increment: 5      # "再推荐几个"的默认增量
  primary_provider: "deepseek"   # 主 LLM 提供商
  backup_provider: "openai"      # 备用 LLM 提供商
  temperature: 0                 # LLM 温度（0 = 确定性输出）

llm:
  deepseek:
    model: "deepseek-chat"
    base_url: "https://api.deepseek.com"
    api_key: "${DEEPSEEK_API_KEY}"
  openai:
    model: "gpt-4o-mini"
    api_key: "${OPENAI_API_KEY}"
```

---

## 9. 安全约束

| 约束 | 说明 |
|------|------|
| API Key 管理 | 通过环境变量注入，不硬编码在代码或配置文件中 |
| Prompt 注入防护 | LLM 天然对 SQL/HTML 注入免疫（不执行代码） |
| PII 处理 | Intent Router 层不处理 PII 脱敏，由 API Layer 负责 |
| Audit Log | 不记录 API Key，不记录 PII 明文 |

---

## 10. 测试约束

| 约束 | 说明 |
|------|------|
| 测试框架 | pytest + pytest-asyncio |
| LLM Mock | 测试时使用 Mock LLM（不调用真实 API） |
| 容器内执行 | 所有测试在 Docker 容器内运行 |
| 测试数据隔离 | 每个测试用例独立的 fixture |
| 覆盖率目标 | 核心逻辑 >= 90% |
| 测试分类 | unit（纯函数）/ integration（LangGraph 流程）/ e2e（含真实 LLM，可选） |
