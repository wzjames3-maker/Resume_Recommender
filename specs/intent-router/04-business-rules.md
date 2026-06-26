<!-- Module: intent-router -->
<!-- Spec Layer: 04 - Business Rules -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 业务规则：Intent Router（意图路由模块）

## 规则总览

| ID | 规则名称 | 类别 | 来源 |
|----|----------|------|------|
| RULE-001 | LLM Function Calling 驱动 | 意图识别 | tech-decision.md |
| RULE-002 | 置信度阈值门控 | 意图识别 | BR-17, NFR-009 |
| RULE-003 | 上文优先 Refine | 多轮对话 | BR-03 |
| RULE-004 | "再推荐几个" → Refine | 多轮对话 | BR-05 |
| RULE-005 | "第一个人" → Lookup | 候选人操作 | BR-14 |
| RULE-006 | "对比" → Compare | 候选人操作 | BR-15 |
| RULE-007 | 排除条件解析 | Slot 提取 | BR-05 |
| RULE-008 | 意图优先级表 | 意图识别 | 02-intent-inventory.md |
| RULE-009 | Slot 增量合并 | 多轮对话 | BR-05 |
| RULE-010 | Slot 同类覆盖 | 多轮对话 | BR-05 |
| RULE-011 | 条件重置 | 多轮对话 | BR-07 |
| RULE-012 | 候选人位置引用 | 候选人操作 | BR-14 |
| RULE-013 | 候选人姓名匹配 | 候选人操作 | BR-14 |
| RULE-014 | Refine 无上文处理 | 多轮对话 | UC-002 EF-001 |
| RULE-015 | Fallback 回复模板 | 兜底 | BR-17 |
| RULE-016 | Audit Log 100% 覆盖 | 审计 | FR-020, NFR-011 |
| RULE-017 | LLM 降级策略 | 容错 | NFR-020 |

---

## 一、意图识别规则

### RULE-001: LLM Function Calling 驱动

Intent 识别和 Slot 提取必须通过 LLM Function Calling + Pydantic Structured Output 实现。

**强制约束**：
- ✅ 使用 `langchain_openai.ChatOpenAI.with_structured_output()` 约束 LLM 输出格式
- ✅ LLM 输出必须通过 `IntentClassificationOutput` Pydantic Schema 校验
- ❌ 禁止使用正则表达式（regex）做 Intent 分类
- ❌ 禁止使用关键词匹配做 Intent 分类
- ❌ 禁止使用关键词列表做 Slot 提取

**理由**：regex/关键词方案准确率低（~60%），无法处理语义模糊和上下文消歧。LLM Function Calling 准确率 >= 90%（NFR-008）。

---

### RULE-002: 置信度阈值门控

当 LLM 返回的 confidence < 0.6 时，必须触发 Fallback。

**规则**：
```
IF confidence < 0.6 THEN
    intent = FALLBACK
    返回引导性回复
END IF
```

**阈值可配置**：通过配置文件 `config.yaml` 中的 `intent.confidence_threshold` 修改。

**不可绕过**：无论任何场景，confidence < 0.6 时不允许路由到业务 Workflow。

---

### RULE-008: 意图优先级表

当 LLM 可能识别出多个意图时，按以下优先级选择（数字越小优先级越高）：

| 优先级 | Intent | 触发条件 |
|--------|--------|----------|
| 1 | `resume.upload` | 包含"上传"/"导入"等明确动作词 |
| 2 | `resume.manage` | 包含"删除"/"重新解析"/"更新"等管理动作 |
| 3 | `recruitment.compare` | 包含"对比"/"比较"/"差异"等比较词 |
| 4 | `candidate.lookup` | 包含"看看"/"详情"/"第X个"/"谁是"等查看词 |
| 5 | `recruitment.refine` | 有上文 + 条件性表达 |
| 6 | `recruitment.search` | 包含"找"/"推荐"/"需要"等招聘词 |
| 7 | `analytics` | 包含"多少"/"统计"/"有几个"等统计词 |
| 8 | `knowledge.qa` | 包含"什么是"/"薪资范围"/"区别"等知识词 |
| 9 | `chat` | 无明确业务意图的对话 |
| 10 | `fallback` | 兜底 |

**使用方式**：优先级表作为 LLM System Prompt 的一部分传入，指导 LLM 在模糊场景下的判断。不允许代码层硬编码优先级覆盖 LLM 输出。

---

## 二、多轮对话规则

### RULE-003: 上文优先 Refine

当 Conversation Memory 中存在上一次 recruitment.search 或 recruitment.refine 的记录，且当前输入是条件性表达时，应优先识别为 `recruitment.refine`。

**条件性表达的特征**：
- 单独的条件词："女生呢"、"学历高一点"、"年龄小一点"
- 增量词："再推荐几个"、"更多"
- 排除词："不要外包"、"排除应届生"
- 排序词："按经验排序"、"薪资从高到低"

**不适用条件**：
- 用户发起了新的招聘需求："找算法工程师"（→ recruitment.search）
- 无对话历史（turn_count == 0）：条件性表达应给出提示（RULE-014）

---

### RULE-004: "再推荐几个"/"更多" → Refine

| 表达 | Intent | Slot 变化 |
|------|--------|-----------|
| "再推荐几个" | `recruitment.refine` | count = last_count + 5 |
| "更多" | `recruitment.refine` | count = last_count + 5 |
| "再推荐20个" | `recruitment.refine` | count = 20（用户指定） |

**注意**："再推荐几个"的默认增量为 5，可通过配置修改。

---

### RULE-005: "第一个人"/"看看张三" → Lookup

| 表达 | Intent | Slot |
|------|--------|------|
| "第一个人" | `candidate.lookup` | candidate_ref = last_candidates[0] |
| "第一个" | `candidate.lookup` | candidate_ref = last_candidates[0] |
| "第二个人" | `candidate.lookup` | candidate_ref = last_candidates[1] |
| "看看张三" | `candidate.lookup` | candidate_ref = name("张三") |
| "张三的简历" | `candidate.lookup` | candidate_ref = name("张三") |
| "他的项目经历" | `candidate.lookup` | candidate_ref = current_candidate（已定位） |

---

### RULE-006: "对比" → Compare

| 表达 | Intent | Slot |
|------|--------|------|
| "对比前两个" | `recruitment.compare` | target = last_candidates[0:2] |
| "张三和李四哪个更合适" | `recruitment.compare` | target = [name("张三"), name("李四")] |
| "这三个人的技能差异" | `recruitment.compare` | target = last_candidates[0:3], dimension = skills |

---

### RULE-009: Slot 增量合并

在 recruitment.refine 场景下，新提取的 Slot 与历史 Slot 增量合并。

```
合并规则:
  FOR each slot in new_slots:
    IF slot is None:
      SKIP  # 不覆盖
    ELSE IF slot is exclude_ type:
      last_slots[slot].append(new_values)  # 追加
    ELSE:
      last_slots[slot] = new_value  # 覆盖
```

---

### RULE-010: Slot 同类覆盖

相同类型的 Slot，新值覆盖旧值。

| 场景 | last_slots | new_slots | merged |
|------|------------|-----------|--------|
| count 覆盖 | count=10 | count=20 | count=20 |
| gender 覆盖 | gender=男 | gender=女 | gender=女 |
| city 覆盖 | city=北京 | city=杭州 | city=杭州 |
| experience 覆盖 | experience=5 | experience=3 | experience=3 |

---

### RULE-011: 条件重置

当用户发起新的 recruitment.search（而非 refine），所有历史 Slot 重置。

**判断条件**：
- Intent 识别为 `recruitment.search`（而非 `recruitment.refine`）
- 用户输入包含明确的岗位/职位描述（非条件性表达）

**执行**：
```
IF intent == RECRUITMENT_SEARCH:
    merged_slots = new_slots  # 完全替换，不合并历史
    last_filters = {}
```

---

### RULE-012: 候选人位置引用

| 表达 | 解析规则 |
|------|----------|
| "第一个人" / "第一个" | last_candidates[0] |
| "第二个人" / "第二个" | last_candidates[1] |
| "最后一个人" | last_candidates[-1] |
| "前两个" | last_candidates[0:2] |
| "这三个" | last_candidates[0:3] |

---

### RULE-013: 候选人姓名匹配

当用户通过姓名引用候选人时，按以下优先级匹配：

1. 在 last_candidates 中按 name 精确匹配
2. 在 last_candidates 中按 name 模糊匹配（包含关系）
3. 在 Resume Store 中按 name 全库搜索（仅 last_candidates 为空时）

**模糊匹配冲突**：匹配到多人时，列出候选项让 HR 选择（UC-003 AF-001）。

---

### RULE-014: Refine 无上文处理

当用户输入为条件性表达，但 Conversation Memory 中无上一次 recruitment.search 记录时：

```
IF intent == RECRUITMENT_REFINE AND turn_count == 0:
    返回: "请先描述您的招聘需求，例如「找5年Java工程师，杭州」"
    intent = FALLBACK（临时，不记录为真正 fallback）
```

---

## 三、Slot 提取规则

### RULE-007: 排除条件解析

否定表达必须转换为 `exclude_` 前缀的 Slot。

| 用户表达 | 解析结果 |
|----------|----------|
| "不要外包" | exclude_job_type = ["外包"] |
| "排除应届生" | exclude_experience = [0]（排除 0 年经验） |
| "不要阿里的人" | exclude_company = ["阿里巴巴"] |
| "除了北京" | exclude_city = ["北京"] |
| "不要Java" | exclude_skills = ["Java"] |
| "学历不要低于本科" | education = "本科"（正向约束，不使用 exclude） |

**合并规则**：排除条件追加到已有排除列表，不覆盖（RULE-009 的特例）。

---

## 四、兜底规则

### RULE-015: Fallback 回复模板

Fallback 时返回标准化的引导性回复：

```
"我是招聘助手，可以帮您：
1. 搜索候选人 — 如「找5年Java工程师，杭州」
2. 上传简历 — 如「上传这份简历」
3. 查看候选人详情 — 如「第一个人是谁」
4. 对比候选人 — 如「对比前两个候选人」

请问有什么需要帮助的？"
```

**要求**：
- 必须包含系统能力简述
- 必须包含 2~4 个示例查询
- 不允许返回空回复或纯错误信息
- 不允许静默吞掉错误

---

## 五、审计规则

### RULE-016: Audit Log 100% 覆盖

**铁律**：100% 的意图识别操作必须有对应的 Audit Log 记录，包括正常识别和异常场景。

| 场景 | 是否记录 | 特殊字段 |
|------|----------|----------|
| 正常识别 | ✅ | 标准字段 |
| Fallback | ✅ | is_fallback=true |
| LLM 超时 | ✅ | error="llm_timeout" |
| 空输入 | ✅ | error="empty_input" |
| 超长输入 | ✅ | error="input_truncated", 原始长度 |

---

## 六、容错规则

### RULE-017: LLM 降级策略

当主 LLM（DeepSeek）不可用时，按以下顺序降级：

```
1. DeepSeek API 调用 → 成功 → 返回结果
2. DeepSeek 超时/失败 → 重试 1 次
3. 重试仍失败 → 切换到 OpenAI 备用 LLM
4. OpenAI 调用 → 成功 → 返回结果
5. OpenAI 也失败 → 返回 Fallback IntentResult
```

**降级时的 Audit Log**：必须记录 `llm_model` 为实际使用的模型，`error` 中记录降级原因。
