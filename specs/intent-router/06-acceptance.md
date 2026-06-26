<!-- Module: intent-router -->
<!-- Spec Layer: 06 - Acceptance Criteria -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 验收标准：Intent Router（意图路由模块）

## 验收标准总览

| ID | 验收标准 | 覆盖需求/规则/边界 | 优先级 |
|----|----------|-------------------|--------|
| AC-001 | 10 类 Intent 正确识别 | REQ-001, RULE-001 | P0 |
| AC-002 | 置信度评估与阈值门控 | REQ-001, RULE-002 | P0 |
| AC-003 | Candidate Slot 提取 | REQ-002 | P0 |
| AC-004 | Query Slot 提取 | REQ-002 | P0 |
| AC-005 | 上下文感知 Refine 识别 | REQ-003, RULE-003, RULE-004 | P0 |
| AC-006 | Slot 增量合并 | REQ-003, RULE-009, RULE-010 | P0 |
| AC-007 | Intent 路由分发 | REQ-004 | P0 |
| AC-008 | Fallback 处理 | REQ-005, RULE-015, EC-006 | P0 |
| AC-009 | Audit Log 完整性 | REQ-006, RULE-016 | P0 |
| AC-010 | 排除条件解析 | REQ-007, RULE-007 | P1 |
| AC-011 | 意图模糊消歧 | EC-001 | P1 |
| AC-012 | Slots 冲突处理 | EC-002, RULE-010 | P1 |
| AC-013 | 无上文 Refine 提示 | EC-003, RULE-014 | P1 |
| AC-014 | LLM 非法输出降级 | EC-004 | P1 |
| AC-015 | LLM 降级策略 | RULE-017, EC-008 | P1 |

---

## AC-001: 10 类 Intent 正确识别

### 覆盖

REQ-001, RULE-001

### 场景

```gherkin
Scenario Outline: 识别各类 Intent
    Given 用户输入为 "<query>"
    And 对话轮次为 0（无上文）
    When 调用 classify_intent
    Then 返回的 intent 应为 "<expected_intent>"
    And confidence 应 >= 0.6

    Examples:
    | query                           | expected_intent          |
    | 找5年Java工程师，杭州             | recruitment.search       |
    | 女生呢                           | recruitment.search       |
    | 对比前两个候选人                   | recruitment.compare      |
    | 第一个人是谁                      | candidate.lookup         |
    | 上传这份简历                      | resume.upload            |
    | 删除张三的简历                    | resume.manage            |
    | Java工程师薪资范围是多少           | knowledge.qa             |
    | 人才库有多少Java工程师             | analytics                |
    | 你好                             | chat                     |
    | asdfghjkl                       | fallback                 |

Scenario: 禁止使用 regex 分类
    Given Intent 识别模块已加载
    Then 模块中不应包含基于正则表达式的 Intent 分类逻辑
    And 意图识别必须通过 LLM Function Calling 实现
```

---

## AC-002: 置信度评估与阈值门控

### 覆盖

REQ-001, RULE-002

### 场景

```gherkin
Scenario: 高置信度正常路由
    Given LLM 返回 confidence = 0.85
    When 检查置信度阈值
    Then intent 保持 LLM 识别结果
    And 正常路由到对应 Workflow

Scenario: 低置信度触发 Fallback
    Given LLM 返回 confidence = 0.4
    When 检查置信度阈值（默认 0.6）
    Then intent 被强制设为 FALLBACK
    And 返回引导性回复
    And is_fallback = true

Scenario: 边界置信度
    Given LLM 返回 confidence = 0.6（恰好等于阈值）
    When 检查置信度阈值
    Then intent 保持 LLM 识别结果（>= 0.6 不触发 fallback）

Scenario: 阈值可配置
    Given 配置文件中 intent.confidence_threshold = 0.7
    And LLM 返回 confidence = 0.65
    When 检查置信度阈值
    Then intent 被强制设为 FALLBACK（0.65 < 0.7）
```

---

## AC-003: Candidate Slot 提取

### 覆盖

REQ-002, 03-slot-definition.md

### 场景

```gherkin
Scenario: 复合表达提取
    Given 用户输入 "找5年Java工程师，杭州，985"
    When 调用 classify_intent
    Then candidate_slots 应包含:
        | slot          | value          |
        | job_title     | Java工程师      |
        | skills        | [Java]         |
        | experience    | 5.0            |
        | experience_op | >=             |
        | city          | 杭州            |
        | education     | 985            |

Scenario: 薪资表达提取
    Given 用户输入 "薪资20k以下的"
    When 调用 classify_intent
    Then candidate_slots 应包含:
        | slot       | value   |
        | salary     | 20000   |
        | salary_op  | <=      |

Scenario: 范围表达提取
    Given 用户输入 "3到5年经验"
    When 调用 classify_intent
    Then candidate_slots 应包含:
        | slot          | value   |
        | experience    | [3, 5]  |
        | experience_op | between |

Scenario: 未提及的 Slot 保持 None
    Given 用户输入 "找Java工程师"
    When 调用 classify_intent
    Then candidate_slots.gender 应为 None
    And candidate_slots.city 应为 None
    And candidate_slots.salary 应为 None
```

---

## AC-004: Query Slot 提取

### 覆盖

REQ-002

### 场景

```gherkin
Scenario: 默认 Query Slot
    Given 用户输入 "找Java工程师"
    When 调用 classify_intent
    Then query_slots 应为默认值:
        | slot    | value  |
        | count   | 10     |
        | sort_by | score  |
        | order   | desc   |
        | page    | 1      |
        | top_k   | 50     |

Scenario: 用户指定数量
    Given 用户输入 "推荐20个Java工程师"
    When 调用 classify_intent
    Then query_slots.count = 20

Scenario: 用户指定排序
    Given 用户输入 "按经验排序"
    When 调用 classify_intent
    Then query_slots.sort_by = experience
```

---

## AC-005: 上下文感知 Refine 识别

### 覆盖

REQ-003, RULE-003, RULE-004

### 场景

```gherkin
Scenario: 有上文时 "女生呢" 识别为 Refine
    Given ConversationContext 中 last_intent = RECRUITMENT_SEARCH
    And last_query = { job_title: "Java工程师", city: "杭州" }
    And turn_count = 1
    When 用户输入 "女生呢"
    And 调用 classify_intent
    Then intent = recruitment.refine
    And candidate_slots.gender = "女"

Scenario: "再推荐几个" 识别为 Refine
    Given ConversationContext 中 last_intent = RECRUITMENT_SEARCH
    And last_query = { count: 10 }
    When 用户输入 "再推荐几个"
    And 调用 classify_intent
    Then intent = recruitment.refine
    And query_slots.count = 15（last_count + 5）

Scenario: "更多" 识别为 Refine
    Given ConversationContext 中 last_intent = RECRUITMENT_SEARCH
    And last_query = { count: 10 }
    When 用户输入 "更多"
    And 调用 classify_intent
    Then intent = recruitment.refine
    And query_slots.count = 15
```

---

## AC-006: Slot 增量合并

### 覆盖

REQ-003, RULE-009, RULE-010

### 场景

```gherkin
Scenario: 增量合并 - 追加新条件
    Given last_slots = { job_title: "Java工程师", city: "杭州" }
    And new_slots = { gender: "女" }
    When 调用 merge_slots(last_slots, new_slots, "incremental")
    Then merged = { job_title: "Java工程师", city: "杭州", gender: "女" }

Scenario: 同类覆盖
    Given last_slots = { count: 10 }
    And new_slots = { count: 20 }
    When 调用 merge_slots(last_slots, new_slots, "incremental")
    Then merged = { count: 20 }

Scenario: 排除追加
    Given last_slots = { skills: ["Java"] }
    And new_slots = { exclude_job_type: ["外包"] }
    When 调用 merge_slots(last_slots, new_slots, "incremental")
    Then merged = { skills: ["Java"], exclude_job_type: ["外包"] }

Scenario: 条件重置
    Given last_slots = { skills: ["Java"], city: "杭州" }
    And new_slots = { job_title: "算法工程师" }
    And intent = RECRUITMENT_SEARCH（新搜索）
    When 调用 merge_slots(last_slots, new_slots, "reset")
    Then merged = { job_title: "算法工程师" }（历史被丢弃）
```

---

## AC-007: Intent 路由分发

### 覆盖

REQ-004

### 场景

```gherkin
Scenario Outline: 每个 Intent 路由到正确 Workflow
    Given IntentResult.intent = "<intent>"
    When 调用 route_intent(state)
    Then 返回 "<workflow>"

    Examples:
    | intent                | workflow              |
    | recruitment.search    | hybrid_search_workflow |
    | recruitment.refine    | refine_workflow        |
    | recruitment.compare   | compare_workflow       |
    | candidate.lookup      | lookup_workflow        |
    | resume.upload         | upload_workflow        |
    | resume.manage         | manage_workflow        |
    | knowledge.qa          | qa_workflow             |
    | analytics             | analytics_workflow     |
    | chat                  | chat_workflow           |
    | fallback              | fallback_workflow      |

Scenario: 未知 Intent 路由到 Fallback
    Given IntentResult.intent = "unknown_intent"（非法值）
    When 调用 route_intent(state)
    Then 返回 "fallback_workflow"
```

---

## AC-008: Fallback 处理

### 覆盖

REQ-005, RULE-015, EC-006

### 场景

```gherkin
Scenario: 低置信度触发 Fallback
    Given LLM 返回 confidence = 0.3
    When 意图识别完成
    Then intent = FALLBACK
    And 返回引导性回复
    And 回复包含系统能力描述
    And 回复包含 2~4 个示例查询
    And 不返回空回复

Scenario: 空输入触发 Fallback（不调用 LLM）
    Given 用户输入 ""（空字符串）
    When 调用 classify_intent
    Then 不调用 LLM API
    And intent = FALLBACK
    And confidence = 0.0
    And 返回标准 Fallback 回复

Scenario: Fallback 事件记录到 Audit Log
    Given 意图识别触发了 Fallback
    When 处理完成
    Then Audit Log 中 is_fallback = true
```

---

## AC-009: Audit Log 完整性

### 覆盖

REQ-006, RULE-016

### 场景

```gherkin
Scenario: 正常识别写入 Audit Log
    Given 用户输入 "找Java工程师"
    When 意图识别完成
    Then Audit Log 包含:
        | field             | 非空 |
        | timestamp         | ✓    |
        | conversation_id   | ✓    |
        | user_id           | ✓    |
        | raw_query         | ✓    |
        | detected_intent   | ✓    |
        | confidence        | ✓    |
        | extracted_slots   | ✓    |
        | latency_ms        | ✓    |
        | llm_model         | ✓    |
        | llm_tokens_used   | ✓    |
        | is_fallback       | ✓    |

Scenario: 异常场景也写入 Audit Log
    Given LLM 调用超时
    When 降级处理完成
    Then Audit Log 中包含 error = "llm_timeout"
    And is_fallback = true

Scenario: Audit Log 不包含 PII
    Given 用户输入中包含手机号 "13812345678"
    When Audit Log 写入
    Then raw_query 中保留原始文本（Intent Router 层不做 PII 脱敏）
    And 注意: PII 脱敏在 API Layer 和 candidate.lookup 中处理
```

---

## AC-010: 排除条件解析

### 覆盖

REQ-007, RULE-007

### 场景

```gherkin
Scenario: "不要外包" 解析为排除条件
    Given 用户输入 "不要外包"
    And 有上文（refine 场景）
    When 调用 classify_intent
    Then candidate_slots.exclude_job_type = ["外包"]

Scenario: 多个排除条件追加
    Given 已有 exclude_job_type = ["外包"]
    And 用户输入 "也不要实习生"
    When 调用 merge_slots
    Then exclude_job_type = ["外包", "实习"]

Scenario: "学历不要低于本科" 解析为正向约束
    Given 用户输入 "学历不要低于本科"
    When 调用 classify_intent
    Then candidate_slots.education = "本科"（正向约束）
    And 不生成 exclude_education
```

---

## AC-011: 意图模糊消歧

### 覆盖

EC-001

### 场景

```gherkin
Scenario: 短输入有上文时用上下文消歧
    Given 用户输入 "Java"
    And ConversationContext 中 last_intent = RECRUITMENT_SEARCH
    When 调用 classify_intent
    Then intent = recruitment.refine
    And confidence > 0.5

Scenario: 短输入无上文时默认 search
    Given 用户输入 "Java"
    And ConversationContext 中 turn_count = 0
    When 调用 classify_intent
    Then intent = recruitment.search（系统默认场景）
    And confidence 可能低于 0.6 → 触发 Fallback
```

---

## AC-012: Slots 冲突处理

### 覆盖

EC-002, RULE-010

### 场景

```gherkin
Scenario: 同一句中 count 冲突
    Given 用户输入 "推荐10个，不20个吧"
    When 调用 classify_intent
    Then query_slots.count = 20（后者覆盖）

Scenario: 同一句中 city 冲突
    Given 用户输入 "找杭州或者北京的"
    When 调用 classify_intent
    Then 取最后出现的 city 或按 LLM 理解处理
```

---

## AC-013: 无上文 Refine 提示

### 覆盖

EC-003, RULE-014

### 场景

```gherkin
Scenario: 首轮对话发送条件性表达
    Given turn_count = 0
    And 用户输入 "女生呢"
    When 调用 classify_intent
    Then intent = FALLBACK
    And 返回: "请先描述您的招聘需求..."
    And 不消耗 LLM Token（短路处理，如果可以判断）

Scenario: 首轮完整查询不触发此规则
    Given turn_count = 0
    And 用户输入 "推荐几个Java工程师"
    When 调用 classify_intent
    Then intent = recruitment.search（正常识别）
```

---

## AC-014: LLM 非法输出降级

### 覆盖

EC-004

### 场景

```gherkin
Scenario: LLM 返回非法 Intent 值
    Given LLM 输出 intent = "search_resume"（不在枚举中）
    When Pydantic 校验
    Then 校验失败
    And intent 被设为 FALLBACK
    And confidence = 0.0
    And Audit Log 记录 error = "invalid_intent"

Scenario: LLM 输出缺少必填字段
    Given LLM 输出缺少 confidence 字段
    When Pydantic 校验
    Then 校验失败
    And intent 被设为 FALLBACK
```

---

## AC-015: LLM 降级策略

### 覆盖

RULE-017, EC-008

### 场景

```gherkin
Scenario: DeepSeek 超时降级到 OpenAI
    Given DeepSeek API 响应时间 > 10s
    When 重试 1 次仍超时
    Then 自动切换到 OpenAI 备用 LLM
    And OpenAI 返回正常结果
    And Audit Log 中 llm_model = "gpt-4o-mini"
    And Audit Log 中记录降级原因

Scenario: 双 LLM 均失败
    Given DeepSeek 超时
    And OpenAI 也超时
    When 降级链耗尽
    Then intent = FALLBACK
    And confidence = 0.0
    And Audit Log 中 error = "llm_all_failed"
    And 返回标准 Fallback 回复
```
