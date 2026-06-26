<!-- Module: intent-router -->
<!-- Spec Layer: 05 - Edge Cases -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 边界情况与异常处理：Intent Router（意图路由模块）

## 边界情况总览

| ID | 场景 | 严重级别 | 处理策略 |
|----|------|----------|----------|
| EC-001 | 意图模糊 | 高 | 上下文消歧 → 默认 search |
| EC-002 | Slots 冲突 | 中 | 后者覆盖前者 |
| EC-003 | 无上文的 Refine | 中 | 提示先描述需求 |
| EC-004 | LLM 返回非法 Intent | 高 | 降级到 fallback |
| EC-005 | 多意图混合 | 中 | 取第一个 |
| EC-006 | 空输入 | 低 | 返回 fallback |
| EC-007 | 超长输入 | 低 | 截断后处理 |
| EC-008 | LLM 超时 | 高 | 重试 → 降级 → fallback |
| EC-009 | LLM 幻觉 Slots | 高 | Pydantic 校验拦截 |
| EC-010 | 候选人引用越界 | 中 | 提示候选人数量 |
| EC-011 | 姓名匹配多人 | 中 | 列出让用户选择 |
| EC-012 | 上下文过期 | 中 | 按首轮对话处理 |
| EC-013 | 特殊字符输入 | 低 | 正常传给 LLM |
| EC-014 | 中英混合输入 | 中 | LLM 原生支持 |
| EC-015 | 纯标点/emoji 输入 | 低 | 识别为 chat 或 fallback |

---

## EC-001: 意图模糊

### 场景

用户输入"Java"，可能是 `recruitment.search`（找 Java 工程师）也可能是 `knowledge.qa`（Java 是什么语言）。

### 触发条件

用户输入过于简短或含义不明确，LLM 置信度在 0.4~0.6 之间。

### 处理策略

```
IF 有对话上文 (turn_count > 0):
    IF last_intent in [RECRUITMENT_SEARCH, RECRUITMENT_REFINE]:
        → 使用上下文推断为 recruitment.search
        → LLM System Prompt 中注入上下文信息辅助判断
    ELSE:
        → 按意图优先级表判断
ELSE:
    → 默认识别为 recruitment.search（HR 系统的默认场景）
    → confidence 保持 LLM 原始值，不人为调高
```

### 示例

| 输入 | 上文 | 识别结果 | 说明 |
|------|------|----------|------|
| "Java" | 无 | `recruitment.search`, confidence=0.55 | 有下限，但低于阈值会 fallback |
| "Java" | last=search("找后端") | `recruitment.refine`, confidence=0.7 | 上下文辅助，更确定 |
| "Java" | last=qa("什么是Python") | `knowledge.qa`, confidence=0.6 | 上下文辅助 |

---

## EC-002: Slots 冲突

### 场景

用户在同一句话中输入了矛盾的 Slot 值，如 "找5年到3年经验的 Java 工程师"。

### 触发条件

同一 Slot 字段出现多个矛盾值。

### 处理策略

```
原则: 后者覆盖前者（位置靠后的值优先）

IF 同一 slot 出现矛盾值:
    取后出现的值
    在 Audit Log 中记录 slot_conflict=true
```

### 示例

| 输入 | 冲突 | 处理结果 |
|------|------|----------|
| "5年到3年经验" | experience: 5 vs 3 | experience=3, experience_op=between（取范围 [3,5]） |
| "10个20个推荐" | count: 10 vs 20 | count=20 |
| "杭州和北京" | city: 杭州 vs 北京 | city=["杭州", "北京"]（如支持多城市）或取最后出现的 city="北京" |

---

## EC-003: 无上文的 Refine

### 场景

用户在首轮对话就发送了条件性表达（如 "女生呢"、"再推荐几个"）。

### 触发条件

- turn_count == 0（Conversation Memory 中无历史）
- 当前输入为条件性表达（缺少主语/岗位描述）

### 处理策略

```
IF turn_count == 0 AND 输入为条件性表达:
    intent = FALLBACK
    返回: "请先描述您的招聘需求，例如「找5年Java工程师，杭州」，然后再补充具体条件。"
    is_fallback = true（但 fallback_reason = "refine_without_context"）
```

### 不适用条件

以下表达即使无上文也不算 Refine：
- "推荐几个Java工程师" → 完整的 recruitment.search
- "上传简历" → resume.upload
- "你好" → chat

---

## EC-004: LLM 返回非法 Intent

### 场景

LLM 返回了不在 IntentEnum 枚举中的值，如 intent="search_resume" 或 intent="unknown"。

### 触发条件

Pydantic 校验 `IntentResult` 时抛出 `ValidationError`。

### 处理策略

```
TRY:
    result = IntentResult.model_validate(llm_output)
EXCEPT ValidationError:
    result = IntentResult(
        intent=FALLBACK,
        confidence=0.0,
        raw_query=query,
        reasoning=f"LLM 返回非法 Intent: {llm_output.intent}, 降级为 Fallback"
    )
    Audit Log 记录 error="invalid_intent"
```

---

## EC-005: 多意图混合

### 场景

用户一句话包含多个意图，如 "找Java工程师，顺便上传这份简历"。

### 触发条件

LLM 识别出输入中包含多个可分离的意图表达。

### 处理策略

```
原则: 取第一个意图（按用户输入的语序）

LLM System Prompt 中明确指示:
"当用户输入包含多个意图时，只识别第一个（最先表达的）意图。"
```

### 示例

| 输入 | 第一个意图 | 丢弃 |
|------|-----------|------|
| "找Java工程师，顺便上传这份简历" | `recruitment.search` | resume.upload |
| "对比前两个候选人，然后找算法工程师" | `recruitment.compare` | recruitment.search |
| "删除张三的简历，再推荐几个后端" | `resume.manage` | recruitment.refine |

### 后续处理

仅处理第一个意图。用户需要单独发起第二个意图的请求。

---

## EC-006: 空输入

### 场景

用户发送了空消息、纯空格、或纯换行。

### 触发条件

`query.strip() == ""`

### 处理策略

```
IF query.strip() == "":
    直接返回 Fallback（不调用 LLM）
    intent = FALLBACK
    confidence = 0.0
    返回标准 Fallback 回复模板
    Audit Log 记录 error="empty_input"
```

### 注意

- 空输入不消耗 LLM Token
- 不写入 Conversation Memory（避免污染上下文）

---

## EC-007: 超长输入

### 场景

用户粘贴了大段文本（>2000 字），可能包含完整的 JD、长篇描述等。

### 触发条件

`len(query) > 2000`

### 处理策略

```
IF len(query) > 2000:
    truncated_query = query[:2000]  # 前 2000 字
    使用 truncated_query 进行意图识别
    Audit Log 记录:
        error="input_truncated"
        original_length=len(query)
        truncated_length=2000
```

### 注意

- 截断点在字符边界，不破坏中文字符
- 截断后正常走 LLM 识别流程
- 不提示用户"输入已截断"（避免打扰）

---

## EC-008: LLM 超时

### 场景

LLM API 调用超过响应时间限制。

### 触发条件

LLM API 响应时间 > 10 秒。

### 处理策略

```
TRY:
    result = await llm.ainvoke(messages)
EXCEPT TimeoutError:
    # 第一次超时，重试
    TRY:
        result = await llm.ainvoke(messages)  # 重试 1 次
    EXCEPT TimeoutError:
        # 重试仍失败，降级到备用 LLM
        TRY:
            result = await backup_llm.ainvoke(messages)
        EXCEPT:
            # 备用 LLM 也失败，返回 Fallback
            result = Fallback IntentResult
            Audit Log 记录 error="llm_all_failed"
```

### 降级链

```
DeepSeek（主）→ 重试 DeepSeek → OpenAI（备）→ Fallback
```

---

## EC-009: LLM 幻觉 Slots

### 场景

LLM 提取了用户输入中不存在的 Slot 值（幻觉），如用户说 "找Java工程师" 但 LLM 提取了 city="北京"。

### 触发条件

LLM 输出的 Slot 值在原始输入中找不到依据。

### 处理策略

```
# Pydantic Schema 的类型约束可以拦截部分幻觉（如非法枚举值）
# 但对于合法值的幻觉（如错误的 city），依赖以下策略:

1. Pydantic 枚举约束 — 拦截非法枚举值
2. 类型约束 — 拦截类型不匹配
3. 范围约束 — 拦截超出范围的数值
4. 对于合法值的幻觉 — V1 不做额外校验（依赖 LLM 准确性）
   V2 可引入 Slot 值回溯校验（检查 Slot 值是否在用户输入中有文本依据）
```

---

## EC-010: 候选人引用越界

### 场景

用户引用了超出 last_candidates 范围的候选人，如 "第十个人" 但上次只推荐了 5 人。

### 触发条件

`position >= len(last_candidates)`

### 处理策略

```
IF position >= len(last_candidates):
    返回: "上次推荐了 {len(last_candidates)} 位候选人，请指定 1~{len(last_candidates)} 的编号。"
    intent 保持 candidate.lookup（不变为 fallback）
    记录到 Audit Log: warning="candidate_index_out_of_range"
```

---

## EC-011: 姓名匹配多人

### 场景

用户说 "看看张三"，但 last_candidates 中有 2 个叫 "张三" 的候选人。

### 触发条件

姓名匹配结果 > 1 人。

### 处理策略

```
IF 姓名匹配到多人:
    返回: "找到 {n} 位名为「张三」的候选人：
    1. 张三 — Java工程师，5年经验
    2. 张三 — 算法工程师，3年经验
    请问您想查看哪一位？"
```

---

## EC-012: 上下文过期

### 场景

Conversation Memory 中的上下文已过期（超过 TTL）或被清除。

### 触发条件

`conversation_context` 为空或 `turn_count == 0`（系统判断为新会话）。

### 处理策略

```
IF 上下文不可用:
    按首轮对话处理
    条件性表达（refine 类）按 EC-003 处理
    非条件性表达正常识别
```

---

## EC-013: 特殊字符输入

### 场景

用户输入包含特殊字符、HTML 标签、SQL 注入尝试等。

### 处理策略

```
# 不做预处理过滤，直接传给 LLM
# LLM 天然能理解这些不是有效查询

# 唯一的预处理: strip 首尾空白
query = query.strip()

# SQL/HTML 注入: LLM 不执行代码，无注入风险
# 特殊字符: LLM 能正常处理
```

---

## EC-014: 中英混合输入

### 场景

用户输入中英文混合，如 "找 3 years Java developer, 杭州"。

### 处理策略

```
# LLM（DeepSeek/GPT）原生支持中英混合输入
# 无需额外处理，直接传给 LLM

# Slot 提取时:
# - 英文 skill 名保持原样: "Java", "Spring Boot"
# - 中文 city 名保持原样: "杭州"
# - 数字经验年限正常解析: "3 years" → experience=3
```

---

## EC-015: 纯标点/emoji 输入

### 场景

用户输入 "????"、"。。。"、"👍" 等无实际语义内容。

### 处理策略

```
IF 输入不含任何有效文字（仅标点/emoji/数字序列）:
    intent = CHAT 或 FALLBACK
    # LLM 通常会将此类输入识别为 CHAT 或低 confidence
    # 如果 confidence < 0.6，走 Fallback 流程
```
