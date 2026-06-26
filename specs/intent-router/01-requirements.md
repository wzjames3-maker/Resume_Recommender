<!-- Module: intent-router -->
<!-- Spec Layer: 01 - Requirements -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 功能需求：Intent Router（意图路由模块）

## 需求总览

| ID | 需求名称 | 优先级 | 关联 PRD |
|----|----------|--------|----------|
| REQ-001 | Intent 识别 | P0 | FR-001, UC-001~UC-008 |
| REQ-002 | Slot 提取 | P0 | FR-001, UC-001, UC-002 |
| REQ-003 | 上下文感知 Intent 识别 | P0 | FR-006, FR-007, UC-002 |
| REQ-004 | Intent 路由分发 | P0 | UC-001~UC-008 |
| REQ-005 | Fallback 处理 | P0 | BR-17, NFR-009 |
| REQ-006 | Audit Log 写入 | P0 | FR-020, NFR-011 |
| REQ-007 | 排除条件处理 | P1 | BR-05, UC-002 |

---

## REQ-001: Intent 识别

### 描述

系统必须能从用户的自然语言输入中识别出 10 类 Intent 中的一个。

### Intent 清单

| Intent 标识 | 中文描述 | 触发 Workflow | 优先级 |
|-------------|----------|---------------|--------|
| `recruitment.search` | 初始招聘检索 | Hybrid Search | P0 |
| `recruitment.refine` | 条件修正 | Filter Last Result | P0 |
| `recruitment.compare` | 候选人对比 | Candidate Compare | P1 |
| `candidate.lookup` | 候选人详情 | Resume Detail | P1 |
| `resume.upload` | 简历上传 | Resume Parser | P0 |
| `resume.manage` | 简历管理 | Resume Management | P2 |
| `knowledge.qa` | 知识问答 | Knowledge RAG | P2 |
| `analytics` | 数据统计 | Statistics | P2 |
| `chat` | 闲聊 | Chat | P3 |
| `fallback` | 兜底 | Recovery | P0 |

### 验收条件

- [ ] 系统能正确识别 10 类 Intent 中的每一类
- [ ] 识别使用 LLM Function Calling + Pydantic Structured Output，不使用 regex
- [ ] 每次识别输出置信度分数（confidence: float, 0.0~1.0）
- [ ] 置信度阈值可配置，默认 0.6

### 来源

PRD FR-001, 02-intent-inventory.md, NFR-008

---

## REQ-002: Slot 提取

### 描述

系统在识别 Intent 的同时，必须从用户输入中提取结构化参数（Slots）。Slot 分为三类：

### Candidate Slot（候选人属性，17 个字段）

| Slot | 类型 | 必填 | 说明 |
|------|------|------|------|
| job_title | string | 是 | 目标岗位 |
| skills | string[] | 否 | 技能列表 |
| experience | number | 否 | 工作年限 |
| experience_op | enum | 否 | 年限比较运算符（>=, <=, =, between） |
| education | enum | 否 | 学历要求 |
| gender | enum | 否 | 性别 |
| age | number | 否 | 年龄 |
| age_op | enum | 否 | 年龄比较运算符 |
| city | string | 否 | 工作城市 |
| industry | string | 否 | 行业经验 |
| company | string | 否 | 公司经历 |
| school | string | 否 | 毕业学校 |
| salary | number | 否 | 期望薪资 |
| salary_op | enum | 否 | 薪资比较运算符 |
| language | string[] | 否 | 语言能力 |
| certificate | string[] | 否 | 证书资质 |
| job_type | enum | 否 | 用工形式 |

### Query Slot（查询控制，5 个字段）

| Slot | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| count | integer | 10 | 推荐数量 |
| sort_by | enum | score | 排序字段 |
| order | enum | desc | 排序方向 |
| page | integer | 1 | 页码 |
| top_k | integer | 50 | 检索召回数量 |

### 验收条件

- [ ] 能从自然语言中提取 Candidate Slot 和 Query Slot
- [ ] 复合表达正确解析（如 "5年Java工程师" → experience=5, experience_op=>=, skills=[Java]）
- [ ] 未提及的 Slot 保持 None，不填充默认值（Query Slot 除外）
- [ ] Query Slot 使用默认值填充

### 来源

03-slot-definition.md, PRD FR-001

---

## REQ-003: 上下文感知 Intent 识别

### 描述

在多轮对话场景下，系统必须结合 Conversation Memory 中的上下文信息进行意图识别和 Slot 提取。

### 规则

1. **有上文时优先判断 refine** — 如果 Conversation Memory 中存在上一次 recruitment.search，且当前输入是条件性表达（如"女生呢"、"再推荐几个"），应识别为 `recruitment.refine`（BR-03）
2. **Slot 增量合并** — refine 场景下，新 Slot 与 last_filters 增量合并，同类覆盖，异类追加（BR-05）
3. **条件重置** — 如果用户发起新的 recruitment.search（如"找算法工程师"），重置所有历史 filters（BR-07）
4. **候选人引用** — candidate.lookup 需要从 last_candidates 中定位目标候选人

### 需要从 Conversation Memory 获取的上下文

| 字段 | 说明 | 用途 |
|------|------|------|
| last_query | 上一次查询的完整 Slots | refine 时的合并基础 |
| last_filters | 上一次生效的过滤条件 | refine 时的合并基础 |
| last_candidates | 上一次推荐的候选人列表 | candidate.lookup 定位、recruitment.compare 选择 |
| turn_count | 当前对话轮次 | 判断是否为首轮对话 |
| intent_history | 历史意图序列 | 辅助意图消歧 |

### 验收条件

- [ ] 有上文时，"女生呢" 正确识别为 recruitment.refine，而非 recruitment.search
- [ ] 有上文时，"再推荐几个" 正确识别为 recruitment.refine
- [ ] 无上文时，"女生呢" 给出提示 "请先描述您的招聘需求"
- [ ] Slot 增量合并正确：新条件追加，同类覆盖

### 来源

PRD FR-006, FR-007, UC-002, 03-slot-definition.md, BR-03, BR-05, BR-07

---

## REQ-004: Intent 路由分发

### 描述

系统必须根据识别出的 Intent，通过 LangGraph Conditional Edge 将请求分发到对应的下游 Workflow 节点。

### 路由映射

| Intent | 路由目标 Workflow | 说明 |
|--------|-------------------|------|
| `recruitment.search` | `hybrid_search_workflow` | 初始检索 |
| `recruitment.refine` | `refine_workflow` | 条件修正后检索 |
| `recruitment.compare` | `compare_workflow` | 多候选人对比 |
| `candidate.lookup` | `lookup_workflow` | 候选人详情 |
| `resume.upload` | `upload_workflow` | 简历解析入库 |
| `resume.manage` | `manage_workflow` | 简历 CRUD |
| `knowledge.qa` | `qa_workflow` | 知识问答 |
| `analytics` | `analytics_workflow` | 数据统计 |
| `chat` | `chat_workflow` | 闲聊回复 |
| `fallback` | `fallback_workflow` | 引导性回复 |

### 验收条件

- [ ] 每个 Intent 都有且仅有一个路由目标
- [ ] 路由通过 LangGraph Conditional Edge 实现
- [ ] 路由决策基于 IntentResult 中的 intent 字段
- [ ] 新增 Intent 只需在路由映射表中添加，不需要修改路由逻辑

### 来源

PRD UC-001~UC-008, 02-intent-inventory.md

---

## REQ-005: Fallback 处理

### 描述

当意图识别置信度低于阈值（默认 0.6）时，系统必须触发 Fallback 流程，返回引导性回复。

### Fallback 触发条件

| 条件 | 说明 |
|------|------|
| confidence < 0.6 | LLM 返回的置信度低于阈值 |
| LLM 返回非法 Intent | Intent 值不在 10 类枚举中 |
| LLM 调用异常 | 超时、限流、返回格式错误 |
| 空输入 | 用户发送空消息 |
| 输入过长 | 超过 2000 字 |

### Fallback 回复模板

```
"我是招聘助手，可以帮您：
1. 搜索候选人 — 如「找5年Java工程师，杭州」
2. 上传简历 — 如「上传这份简历」
3. 查看候选人详情 — 如「第一个人是谁」
4. 对比候选人 — 如「对比前两个候选人」

请问有什么需要帮助的？"
```

### 验收条件

- [ ] confidence < 0.6 时触发 Fallback
- [ ] Fallback 回复包含系统能力引导
- [ ] Fallback 不静默失败，必须返回回复
- [ ] Fallback 事件记录到 Audit Log

### 来源

BR-17, NFR-009, 02-intent-inventory.md

---

## REQ-006: Audit Log 写入

### 描述

每次意图识别操作必须将结果写入 Audit Log，用于监控、分析和优化。

### 必须记录的字段

| 字段 | 类型 | 说明 |
|------|------|------|
| timestamp | datetime | 请求时间（UTC） |
| conversation_id | string | 会话 ID |
| user_id | string | 用户 ID |
| raw_query | string | 用户原始输入 |
| detected_intent | string | 识别的 Intent |
| confidence | float | 置信度 |
| extracted_slots | dict | 提取的 Slots |
| latency_ms | int | 识别耗时（毫秒） |
| llm_model | string | 使用的 LLM 模型 |
| llm_tokens_used | int | Token 消耗 |
| is_fallback | bool | 是否触发 Fallback |
| error | string | 异常信息（如有） |

### 验收条件

- [ ] 100% 的意图识别操作都有对应的 Audit Log 记录
- [ ] Audit Log 为结构化 JSON 格式
- [ ] PII 信息不记录到 Audit Log（BR-13）
- [ ] 支持按 conversation_id / user_id / 时间范围查询

### 来源

PRD FR-020, NFR-011, NFR-012

---

## REQ-007: 排除条件处理

### 描述

系统必须能识别用户输入中的否定表达（如"不要外包"、"排除应届生"），并将其转换为 exclude_slot。

### 排除条件表达模式

| 用户表达 | 解析结果 |
|----------|----------|
| "不要外包" | exclude_job_type = ["外包"] |
| "排除应届生" | exclude_experience = [0] |
| "不要阿里的人" | exclude_company = ["阿里巴巴"] |
| "学历不要低于本科" | education_min = "本科"（正向约束） |
| "除了北京" | exclude_city = ["北京"] |

### 规则

1. 排除条件解析为 `exclude_{slot_name}` 格式的字段
2. 排除条件在 Slot 合并时追加到排除列表，不覆盖已有排除
3. 排除条件应用于 Metadata Filter 阶段

### 验收条件

- [ ] "不要外包" 正确解析为 exclude_job_type
- [ ] "排除应届生" 正确解析为 exclude 范围
- [ ] 多个排除条件正确追加（不覆盖）
- [ ] 排除条件在 refine 合并时正确传递

### 来源

BR-05, UC-002 AF-001, 03-slot-definition.md

---
## v1.2-data-pipeline 新增 (2026-06-26)
| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-007 | FR-001 | 简化: 移除 Handler 体系死代码（SearchHandler/RefineHandler/LookupHandler 等桩实现），chat.py 使用显式意图→函数映射表 | P1 |
| REQ-008 | FR-001 | chat.py 未实现意图的引导消息按意图类型返回差异化提示（非统一回复） | P2 |

## v1.3-data-pipeline 新增 (2026-06-26)
| ID | 对应 PRD | 描述 | 优先级 |
|----|----------|------|--------|
| REQ-014 | FR-001 | 修复 segmenter 双匹配：匹配 section type 后 break 外层循环，防止一个 section 被标记为多个类型 | P1 |
| REQ-015 | FR-001 | _dense_to_sparse() 标注为降级实现（非原生 BGE-M3 sparse），API 支持原生 sparse 时自动切换 | P1 |
| REQ-016 | FR-001 | classifier._call_llm() 移除不可达代码（for循环后的 return 语句） | P2 |
