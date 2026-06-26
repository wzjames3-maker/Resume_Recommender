<!-- Module: intent-router -->
<!-- Spec Layer: 03 - API Contract -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 内部接口契约：Intent Router（意图路由模块）

## 接口总览

Intent Router 不对外暴露 HTTP 接口，仅提供**内部函数级接口**供 LangGraph Node 和 API Layer 调用。

| 接口 | 调用方 | 返回类型 | 说明 |
|------|--------|----------|------|
| `classify_intent` | LangGraph Node | `IntentResult` | Intent 识别 + Slot 提取 |
| `extract_slots` | classify_intent 内部 | `CandidateSlot + QuerySlot` | 从 LLM 输出解析 Slots |
| `route_intent` | LangGraph Conditional Edge | `str`（Workflow 名称） | 路由到对应 Workflow |
| `merge_slots` | refine Workflow | `dict` | 合并新旧 Slots |
| `build_context_prompt` | classify_intent 内部 | `list[BaseMessage]` | 构建含上下文的 Prompt |

---

## 接口 1: classify_intent

### 签名

```python
async def classify_intent(
    query: str,
    context: ConversationContext,
    *,
    llm_provider: str = "deepseek",  # "deepseek" | "openai"
) -> IntentResult:
```

### 描述

Intent Router 的核心接口。接收用户输入和对话上下文，调用 LLM 进行意图识别和 Slot 提取，返回结构化的 IntentResult。

### 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| query | `str` | 是 | - | 用户输入的自然语言文本 |
| context | `ConversationContext` | 是 | - | 从 Conversation Memory 获取的对话上下文 |
| llm_provider | `str` | 否 | `"deepseek"` | LLM 提供商选择 |

### 返回值

```python
IntentResult(
    intent=IntentEnum,          # 识别的意图类型
    confidence=0.85,            # 置信度 0.0~1.0
    candidate_slots=CandidateSlot(
        job_title="Java工程师",
        experience=5.0,
        experience_op=">=",
        city="杭州",
        ...
    ),
    query_slots=QuerySlot(
        count=10,
        sort_by="score",
        ...
    ),
    raw_query="找5年Java工程师，杭州",
    reasoning="用户明确表达了招聘需求..."
)
```

### 异常处理

| 异常 | 处理方式 | 返回 |
|------|----------|------|
| LLM 超时（>10s） | 重试 1 次，仍失败则降级 | IntentResult(intent=FALLBACK, confidence=0.0) |
| LLM 返回非法 Intent | Pydantic 校验失败 | IntentResult(intent=FALLBACK, confidence=0.0) |
| LLM API Key 无效 | 切换到备用 provider | 自动重试备用 LLM |
| query 为空 | 短路返回 | IntentResult(intent=FALLBACK, confidence=0.0) |
| query 超长（>2000字） | 截断后处理 | 截断至 2000 字后正常流程 |

### 性能要求

| 指标 | 目标 | 说明 |
|------|------|------|
| P95 延迟 | <= 800ms | 单次 LLM 调用延迟 |
| P99 延迟 | <= 1500ms | 含重试 |
| 重试策略 | 最多重试 1 次 | 首次失败后重试 |

---

## 接口 2: extract_slots

### 签名

```python
def extract_slots(
    llm_output: IntentClassificationOutput,
) -> tuple[CandidateSlot, QuerySlot]:
```

### 描述

从 LLM 的 Structured Output 中解析出 CandidateSlot 和 QuerySlot。这是 classify_intent 的内部辅助函数。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| llm_output | `IntentClassificationOutput` | 是 | LLM Structured Output 的原始输出 |

### 返回值

返回 `(CandidateSlot, QuerySlot)` 元组。

### 处理逻辑

1. 从 `llm_output.candidate_slots` 提取 CandidateSlot
2. 从 `llm_output.query_slots` 提取 QuerySlot
3. QuerySlot 中未指定的字段使用默认值
4. CandidateSlot 中未指定的字段保持 None

---

## 接口 3: route_intent

### 签名

```python
def route_intent(state: IntentRouterState) -> str:
```

### 描述

LangGraph Conditional Edge 函数。根据 IntentResult 中的 intent 字段，返回目标 Workflow 节点名称。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| state | `IntentRouterState` | 是 | LangGraph 当前状态 |

### 返回值

返回目标 Workflow 节点名称（`str`），用于 LangGraph Conditional Edge 路由。

### 路由映射表

```python
ROUTE_MAP: dict[IntentEnum, str] = {
    IntentEnum.RECRUITMENT_SEARCH: "hybrid_search_workflow",
    IntentEnum.RECRUITMENT_REFINE: "refine_workflow",
    IntentEnum.RECRUITMENT_COMPARE: "compare_workflow",
    IntentEnum.CANDIDATE_LOOKUP: "lookup_workflow",
    IntentEnum.RESUME_UPLOAD: "upload_workflow",
    IntentEnum.RESUME_MANAGE: "manage_workflow",
    IntentEnum.KNOWLEDGE_QA: "qa_workflow",
    IntentEnum.ANALYTICS: "analytics_workflow",
    IntentEnum.CHAT: "chat_workflow",
    IntentEnum.FALLBACK: "fallback_workflow",
}
```

### 异常处理

| 异常 | 处理方式 |
|------|----------|
| intent 不在 ROUTE_MAP 中 | 返回 `"fallback_workflow"` |
| state 中无 intent_result | 返回 `"fallback_workflow"` |

---

## 接口 4: merge_slots

### 签名

```python
def merge_slots(
    last_slots: dict,
    new_slots: CandidateSlot,
    merge_type: Literal["incremental", "reset"] = "incremental",
) -> dict:
```

### 描述

合并新旧 Slots。用于 recruitment.refine 场景下将用户的新条件与历史条件合并。

### 参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| last_slots | `dict` | 是 | - | 上一次的 Slots（来自 ConversationContext.last_filters） |
| new_slots | `CandidateSlot` | 是 | - | 本次新提取的 Slots |
| merge_type | `Literal` | 否 | `"incremental"` | 合并方式：incremental（增量）或 reset（重置） |

### 返回值

合并后的 Slots 字典（`dict`）。

### 合并规则

| 场景 | 规则 | 示例 |
|------|------|------|
| 增量合并（incremental） | 新字段追加到已有字段 | last: {skills: ["Java"]} + new: {gender: "女"} → {skills: ["Java"], gender: "女"} |
| 同类覆盖 | 相同字段被新值覆盖 | last: {count: 10} + new: {count: 20} → {count: 20} |
| 排除追加 | exclude_ 字段追加到列表 | last: {exclude_job_type: []} + new: {exclude_job_type: ["外包"]} → {exclude_job_type: ["外包"]} |
| 重置（reset） | 完全丢弃 last_slots，使用 new_slots | last: {skills: ["Java"]} + new: {job_title: "算法工程师"} → {job_title: "算法工程师"} |

---

## 接口 5: build_context_prompt

### 签名

```python
def build_context_prompt(
    query: str,
    context: ConversationContext,
) -> list[BaseMessage]:
```

### 描述

构建包含对话上下文的 LLM Prompt。将 ConversationContext 中的历史信息组装为 System Message 和 Human Message。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | `str` | 是 | 用户当前输入 |
| context | `ConversationContext` | 是 | 对话上下文 |

### 返回值

LangChain Message 列表（`list[BaseMessage]`），可直接传给 LLM。

### Prompt 结构

```
[System Message]
你是企业招聘系统的意图识别引擎。
...

{如果 turn_count > 0}
## 对话历史
上一次查询: {last_query}
上一次过滤条件: {last_filters}
上一次推荐候选人: {last_candidates_summary}
历史意图: {intent_history}
{/如果}

[Human Message]
用户输入: {query}

请识别意图并提取 Slots。
```

---

## 错误码

Intent Router 内部使用的错误码，与 PRD 附录 B 的错误码保持一致。

| 错误码 | 场景 | 处理方式 |
|--------|------|----------|
| `INTENT_RECOGNITION_FAILED` | LLM 返回非法结果 | 返回 Fallback IntentResult |
| `LLM_ERROR` | LLM API 调用失败 | 重试 1 次 → 降级备用 LLM → Fallback |
| `INVALID_INPUT` | 空输入或超长输入 | 空输入 → Fallback；超长 → 截断后重试 |
| `CONTEXT_NOT_FOUND` | Conversation Memory 无记录 | 使用空上下文，按首轮对话处理 |
| `SLOT_MERGE_CONFLICT` | Slot 合并冲突 | 以新值覆盖旧值 |
