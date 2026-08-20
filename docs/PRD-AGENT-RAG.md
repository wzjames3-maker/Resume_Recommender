# 人事子系统 Agent + RAG 设计案（PRD 增补）

> 文档状态：设计与实现参考，更新于 2026-08-18。本文件是 `docs/PRD.md` 的增补案：裁决 §6「AI、知识库与集成边界」的 Agent 化扩展，并在 §9.2 路线表后增补 **D 阶段（Agent 智能化）**。它不推翻 §2.2「人工决策优先」，而是给出该原则的工程化形态（§2）。D1/D2/D3 已在 `apps/hr/agents/`、相关 API 和现有招聘页面中实现，D4 工作台首版已在 `apps/hr/services/agent_workbench.py`、工作台 API 与 `/hr/agents` 页面落地；本文保留设计基线和验收标准，后续变更须同步更新 PRD 与本文件。
>
> 输入依据：① 项目现状勘察（RAG 检索链路与评测、权限审计已交付；Agent 层为零是 2026-08-16 的设计基线，当前 D1/D2/D3 已实现；**ATS v2 目标设计见 `docs/ATS-STATE-MACHINE-V2.md`，传统 ATS 开源调研见 `docs/ATS-OPENSOURCE-REFERENCE.md`，均为 D 阶段前置**）；② 传统 ATS 的 AI Copilot 原则（Harly：context before verbosity / evidence before confidence / propose-confirm-execute / backend-enforced safety）；③ 外部参考架构《Agent + RAG 智能 ATS 系统设计》（propose-approve、证据引用、双表示简历、中心化编排四原则被吸收，技术选型按本项目裁决，见 §13）。

## 0. 结论先行

子系统 = **已有的 RAG 检索服务 + 重构后的 ATS v2 状态机（命令 + 领域事件）** 之间补一层 **Agent 运行时**（`apps/hr/agents/`）：Agent 由事件/人工触发，经白名单工具调用既有检索服务，产出**带证据的提议工件（HrAgentProposal）**，人审批后调用 ATS v2 命令层执行。不引入新框架、新运行时、新向量库；不新增对外通信通道。D1 首期先做一个 Agent：**初筛评估（Screening）**，因为它 100% 复用已交付的检索服务；D2/D3 已在此基础上补齐 JD 起草、Interview Copilot、Sourcing 和沟通草稿；待办队列按 `ATS-DESIGN-SPEC.md` §6 契约补齐后作为建议落点，直接兑现 C 阶段 RAG 投入（recall@5=0.92 目前被 Screening、Sourcing 等多个 Agent 触点复用）。

## 1. 现行 PRD 的问题诊断

PRD 的业务模型、数据边界、PII/审计/生命周期部分是**资产，全部继承**。问题集中在「AI 如何进入流程」这一层：

| # | 问题 | 事实依据 |
|---|---|---|
| 1 | **AI 角色停留在「检索框」**：设计基线时 AI 只出现在自然语言搜人、技能抽取、语义检索三个触点；当前已补齐 Screening、JD 起草、Interview Copilot、Sourcing、沟通草稿，以及评估报告、建议动作和反馈闭环。RAG 已达标（RRF+rerank recall@5=0.92），当前已作为 Screening 和 Sourcing Agent 的证据来源。 | PRD §5.2、§6；`apps/hr/services/resume_search.py` 已交付 |
| 2 | **「人工决策优先」已工程化，以下描述是历史基线**：原则写了「AI 只提供建议」，但建议无数据形态、无审批对象、无决策记录——散落在报告里无法审计、无法度量采纳率、无法迭代。 | PRD §2.2；历史代码中无 proposal/建议工件；当前已落地 HrAgentProposal 和 Proposal 审批接口 |
| 3 | **无 Agent 运行账本**：现有 `ResumeFlowLog` 只覆盖简历入库六节点；`ai_parser.py` 设计基线时三个 LLM 调用是隐形调用；当前已通过 HrAgentRun 统一记录输入摘要、工具链、成本和失败，满足 PRD §6 对外部 LLM 调用记录租户、模型、发送数据类别、用途和失败情况的要求。 | `apps/hr/services/ai_parser.py` |
| 4 | **企业知识库资产未接入**：MaxKB 本职就是企业知识库（JD 模板、面试题库、政策、FAQ），工作区知识库已接入 JD 起草、Interview Copilot 和沟通草稿；这些能力复用白名单知识库，不新增向量库。 | PRD §6；`apps/knowledge` 内核完好 |
| 5 | **路线图已扩展**：D1/D2/D3 已加入并完成实现；当前后续重点是试点观测、阈值冻结和生产灰度。 | PRD §9.2 |
| 6 | **一处原则冲突悬而未决**：业界通行设计（含参考架构）要求「硬条件不满足自动拒、高分自动推进」，与 §2.2 直接冲突。PRD 需要显式裁决而不是回避。 | 本设计 §2 原则 2 给出裁决 |

## 2. 设计原则

1. **可解释 > 黑盒打分**：Agent 每个结论必须携带证据引用（脱敏简历 chunk + 结构化字段核对结果）。无证据不给高分；证据摘录可点击回溯简历原文。
2. **提议-审批（propose-approve），即「人工决策优先」的工程化形态**：Agent 的唯一写出口是 `HrAgentProposal` 工件；一切状态变更由人审批后调 **ATS v2 命令层**执行（操作者=审批人，沿用 ApplicationEvent 时间线与 ATS 命令审计）。零风险产出（报告、草稿、标签）免审批；有风险动作（婉拒、推进）默认必审；D3 才评估对「低风险+高一致性」分带开放可配置免审，且保留审计与人工回滚。
3. **双表示简历**：结构化字段（`Candidate`/`CandidateSkill`，SQL 精确过滤硬条件）+ 语义分块（既有简历语义索引，软条件匹配）——已实现，直接复用，不重复建设。
4. **中心化编排**：不引入 LangGraph/多 Agent 自由协作。Agent = Django 服务 + Celery 任务 + 显式触发器；流程锚定在当前 ATS 的 `Application` 阶段与 `ApplicationEvent` 上，可控、可审计、可重放（`HrAgentRun` 全量留痕）。

## 3. 总体架构

```
┌────────────────────────────────────────────────────────────────┐
│ 接入层  ui/src/views/hr（工作台/候选人/职位/面试/Offer/审计）        │
│         + 新增：AI 报告卡、提议审批、JD/评估草稿（§11）             │
├────────────────────────────────────────────────────────────────┤
│ 业务层  apps/hr 既有服务：候选人/职位/关联状态机/面试/Offer/交接      │
│         权限（HrAccess）与审计（HrAuditLog）贯穿                    │
├────────────────────────────────────────────────────────────────┤
│ Agent 运行时【新增，apps/hr/agents/】                             │
│   触发器（信号/Celery-beat/人工API）→ Runner → 工具注册表（白名单）  │
│   → LLM function calling → 结构化校验 → HrAgentRun + Proposal    │
│   ↕ 工具 = 对既有服务的只读包装；唯一写出口是 propose()              │
├──────────────────────────┬─────────────────────────────────────┤
│ 模型层 apps/models_provider │ 知识层 apps/knowledge               │
│ OpenAI 兼容唯一 Provider：    │ pgvector+tsvector 双路 → RRF(k=60)   │
│ LLM sensenova-6.8-flash-lite│ → bge-reranker-v2-m3 → Small-to-Big │
│ Embedding bge-large-zh-v1.5 │ 简历语义索引(派生数据) + 工作区企业     │
│ Rerank bge-reranker-v2-m3   │ 知识库（MaxKB 本职，复用不新建）        │
├──────────────────────────┴─────────────────────────────────────┤
│ 数据层  PostgreSQL(+pgvector) / Redis / Celery / 对象存储 local|s3 │
└────────────────────────────────────────────────────────────────┘
```

关键决策：**不新增运行时与服务**。Agent 层是 `apps/hr` 内的一个包；MaxKB v2 裁剪时已物理删除的 flow/MCP/工具库**不回引**。

## 4. Agent 运行时设计

### 4.1 组成

- **触发器**（三类）：
  - 事件：`Application` 创建/阶段变更的信号 → Celery 异步（不阻塞业务请求）；
  - 定时：celery-beat（如面试前 Copilot 提醒，D2）；
  - 人工：REST 端点显式触发（`POST /workspace/{ws}/hr/agents/{type}/run`，OPERATOR 起）；SCREENING、INTERVIEW_COPILOT、SOURCING 可接收 `resume_database_ids`，显式范围必须属于当前工作区且处于 ACTIVE。
- **Runner**：组装 system prompt（版本化）+ 上下文 + 工具集 → LLM function calling 循环（工具调用轮次上限 8）→ JSON Schema 校验输出 → 写 `HrAgentRun`，必要时写 `HrAgentProposal`。**D1 第 0 步先做工具调用能力探针**；若 SenseNova 不满足工具调用，降级为「单次结构化规划 + 服务端按固定顺序调用工具」，RAG 链路保持不变。
- **工具注册表**：白名单注册，纯函数包装既有服务；每个工具声明读/写与权限口径。LLM 只能见到注册表内的工具签名。
- **模型配置**：扩展 `HrConfig`（`apps/hr/models/recruitment.py:336`），沿用其 `llm_model_id`/`rerank_model_id`，新增 Agent 开关与阈值（§8）。

### 4.2 工具清单（首期）

| 工具 | 包装的既有实现 | 读/写 | 说明 |
|---|---|---|---|
| `get_job(job_id)` | Job 序列化 | 读 | 含 requirements/skill_requirements；进入 LLM 前做 PII 扫描 |
| `get_candidate_overview(candidate_id)` | Candidate + CandidateSkill | 读 | 仅 id/姓名/城市/学历/年限/技能/状态；**永不包含联系方式、备注、简历原文** |
| `structured_filter(job_id, candidate_id)` | Candidate/CandidateSkill SQL | 读 | 硬条件逐条核对（技能/年限/城市/学历） |
| `search_resumes(query, filters, candidate_id=None, document_ids=None, resume_database_ids=None)` | `resume_search` 服务 | 读 | 复用双路召回→RRF→rerank→Small-to-Big；支持候选人文档集和 resume_database_ids 多库范围限定，默认行为不变 |
| `search_knowledge(kb_ids, query)` | MaxKB 知识库检索 | 读 | 仅 HrConfig 白名单；结果经 PII 扫描与摘要化后才进入 LLM |
| `similar_jobs(job_id)` | SQL 相似 + HIRED 关联聚合 | 读 | 历史录用画像对标；输出不含候选人联系方式 |
| `propose(action, payload)` | 写 `HrAgentProposal` | **写** | **唯一写出口；由 Runner 调用，D1 不暴露给 LLM 自由调用** |

**LLM 上下文投影**：所有工具返回值在进入模型前统一经 `to_llm_context()` 适配器——剔除 phone/email/note/文件路径/简历原文，证据只保留已脱敏 chunk。该层只改工具适配器，**不改 RAG 链路**。

**禁止**：任何直接 UPDATE/DELETE 业务表、发送邮件/IM、创建面试或 Offer。这些能力不存在于工具注册表，LLM 无法触达。

### 4.3 运行账本 `HrAgentRun`

每次运行持久化：`workspace_id`、`agent_type`、`trigger_type`、`ref_object_type/ref_object_id`、`status(PENDING/RUNNING/SUCCEEDED/FAILED/SKIPPED)`、`input_meta`（触发上下文摘要，不含 PII）、`tool_trace`（工具名 + 参数摘要 + 耗时 + 返回条数，脱敏）、`output_json`、`error`、`llm_model`、`prompt_tokens/completion_tokens`、`prompt_version`、`duration_ms`、`create_time`。

该表同时满足三件事：① PRD §6 的 LLM 调用记录义务；② 可重放（input_meta + prompt 版本）；③ 成本观测。现有 `ai_parser.py` 三个隐形 LLM 调用迁入同一账本口径。

### 4.4 幂等、降级、成本护栏与过期

- **幂等与重跑**：事件自动运行用 celery-once 防重，key = `agent_type + ref_object_id`（沿用 `parse_resume_task` 模式）；目标已有 PENDING/RUNNING 任务时跳过。人工触发不受事件锁阻断：目标已有终态 run 后可新建 run；新 Proposal 产生时，同目标旧的 PENDING Proposal 自动 `EXPIRED`。
- **成本护栏**：`agent_enable_screening` 默认关；每工作区 Agent 并发运行数有上限（HrConfig，默认 2）并做触发速率限制；超限 run=SKIPPED + 审计，不无限重试。事件触发仅对 `APPLY`/`REFERRAL` 生效。
- **降级**：LLM 失败/超时重试 2 次后 run=FAILED，**业务零影响**——待办队列照常人工处理，符合 PRD §6「AI 无法提供有效结果时回退结构化筛选」。
- **过期**：Proposal 的目标对象状态已变迁（Application 非 `ACTIVE`，或已离开 Proposal 生成时所在 Stage）→ 自动 `EXPIRED`，不再可审批。

## 5. Agent 清单与优先级

参考架构六 Agent 按本项目边界裁剪为 **5 个 + 2 项明确不做**：

| Agent | 阶段 | 触发 | 职责 | 核心工具 | 审批 | UI 落点 |
|---|---|---|---|---|---|---|
| **Screening 初筛评估** | **D1** | 新建 `ACTIVE` Application（投递/内推，初始 Stage=`APPLIED`）或人工触发 | 人岗匹配评估报告 + 建议动作（§6） | get_job, get_candidate_overview, structured_filter, search_resumes, propose | 建议必审 | 职位页申请卡/AI 抽屉 |
| JD 起草 | D2 | DRAFT 职位人工触发 | 对标知识库 JD 模板 + 历史相似职位，生成 JD 草稿 | search_knowledge, similar_jobs, propose | 草稿免审；写入字段需 HR 确认 | 职位编辑页 |
| Interview Copilot | D2 | 面试创建后/面试前人工触发 | 按简历弱项 + JD 生成结构化面试问题；面后按反馈生成评估草稿 | get_candidate_overview, get_job, search_knowledge(题库), propose | 草稿免审，不自动提交反馈 | my-interviews |
| Sourcing 人才库激活 | D3 | OPEN 职位人工触发 | 检索沉睡候选人生成优先级清单 + 依据 | search_resumes, structured_filter, propose | 只出内部清单，不外发 | 职位详情 |
| 沟通草稿助手 | D3 | 阶段流转/人工触发 | 拒信/进度通知/答疑话术草稿（FAQ 挂企业知识库） | search_knowledge, propose | 草稿免审；**外发永远人工** | 职位页申请操作/沟通抽屉 |

**边界外（明确不做）**：

| 参考架构能力 | 不做的理由 |
|---|---|
| Scheduling Agent（日历集成、邮件多轮敲定时间） | 本产品是**内部工作台**：无日历集成、无候选人端双向通道。远期如有需要，以 Handoff WEBHOOK 同类机制外接，不内置。 |
| 候选人投递端 / 自动外发邮件 | PRD §1 数据边界（候选人数据不进通用通道）+ 渠道能力缺失；自动外发与 §2.2 冲突。 |
| Offer 定价/自动审批 | Offer 审批已有人工流（approval_status + approver_id），AI 不介入金额。 |

## 6. Screening Agent 详细设计（D1 核心）

### 6.1 流程

```
新建 Application(ACTIVE, Stage=APPLIED) → 信号 → Celery → Runner
  ① get_job：拆出硬条件（技能/年限/城市/学历 → 结构化核对）
             与软条件（职责/领域/项目经验 → 语义匹配）
  ② structured_filter：硬条件逐条核对，输出满足/缺失明细
  ③ search_resumes(query, candidate_id=候选人ID, document_ids=该候选人已索引简历文档集)：
             对每条软条件仅在该候选人简历内检索脱敏 chunk 证据（复用 RRF+rerank，召回入口限集）
  ④ similar_jobs（可选）：历史录用画像对标
  ⑤ Runner 服务端评分/派生建议动作 → propose 写 HrAgentProposal（见 6.2，LLM 不直接写提案）
HR 在待办/详情页审批：接受 → ATS v2 命令层执行 `move_stage(next)` / `reject(NOT_FIT)`；忽略 → 人工处理
```

### 6.2 输出 Schema（`proposal.payload_json`）

LLM 只输出评估事实，**不输出 score / suggested_action**；两者由服务端按 §6.3 固定函数派生，写入 `payload_json.decision`。

```json
{
  "hard_conditions": [{"requirement": "≥5 年", "field": "years_experience", "met": true}],
  "dimensions": [
    {"name": "技能匹配", "verdict": "...",
     "evidence": [{"resume_file_id": "", "paragraph_id": "", "excerpt": "（脱敏摘录）", "relevance": 0.83}],
     "confidence": 0.0}
  ],
  "concerns": ["..."],
  "clarifying_questions": ["..."],
  "decision": {
    "score": 0,
    "suggested_action": "ADVANCE | HOLD | DECLINE",
    "hard_met": true,
    "evidence_ok": true,
    "score_version": "v1"
  }
}
```

### 6.3 服务端评分与动作（默认值进 HrConfig，D1 用独立标定集标定后固化）

评分函数版本化为 `score_version`，服务端强制计算；LLM 输出的 `score/action` 一律由 Schema 拒绝：

1. `evidence_strength(d) = 0`（无 evidence），否则 `min(1.0, max(relevance) + 0.05 × (evidence 数 - 1))`。
2. `dimension_score = confidence × evidence_strength`；白名单外维度剔除并写 run 警告。
3. `score = round(100 × mean(通过校验的维度 dimension_score))`；无任何有效维度时 `score = null`。
4. `hard_met` 只由 `structured_filter` 结果决定；`required_dims_ok` = 必评维度（技能匹配、经验相关性）均存在且有 evidence；`evidence_ok` = `required_dims_ok` 且至少两个维度有 evidence 且 `max(relevance) ≥ 0.3`。

| 服务端判定条件 | 建议动作 | 人审批后执行 |
|---|---|---|
| `hard_met` 且 `score ≥ 80` 且 `evidence_ok` | ADVANCE | 一键确认 → `Application.move_stage(next stage)` |
| `hard_met` 且（60 ≤ score < 80 或 `!evidence_ok`） | HOLD | 转人工，附 concerns + clarifying_questions（可生成补充信息话术草稿，D3） |
| `score` 非空且 < 60，或 `!hard_met` | DECLINE | 人工确认 → `REJECTED` + 受控原因 |
| `score = null` / 检索空结果 | HOLD + 原因 | **禁止无证据高分**（提示词禁令 + 服务端校验：无 evidence 维度不得贡献正分） |

### 6.4 提示词骨架（适配版）

```
你是招聘初筛助手，对候选人 X 与职位 Y 做匹配评估。
1. 从 get_job 结果拆出硬性条件与软性条件；硬性条件只用 structured_filter 核对，不做语义判断。
2. 对每条软性条件调用 search_resumes 检索候选人相关经历片段作为证据；证据必须摘录原文。
3. 可用 similar_jobs 检索历史录用画像作对标参考，但不得作为唯一依据。
4. 按给定 JSON Schema 输出评估事实；**不得输出 score 或 suggested_action**；每个维度的结论必须引用至少一条证据或明确标注 confidence < 0.5。
禁止：以姓名、性别、年龄、婚育、民族、院校出身作为评价依据；评价维度仅限白名单
（技能匹配、经验相关性、工作年限、城市、学历——学历仅当 JD 明确要求时使用）；
禁止在证据不足时给出高分或确定性结论；禁止编造简历中不存在的内容。
```

### 6.5 公平性与证据约束

- **维度白名单**在服务端强制：输出维度不在白名单内 → 剔除并写 run 警告；与 PRD §2.2 数据最小化（自由文本不得记录敏感属性）同源。
- 证据摘录全部来自**已脱敏 chunk**（入库管道 PII 掩码 + 残留扫描的前置成果），联系方式不可能进入 LLM 上下文或报告。
- 分组偏差审计（D3）：按分数带 × 渠道/来源统计建议分布，异常分带复查提示词。

## 7. 知识与检索层（复用，不新建）

| 语料 | 现状 | 本设计中的用途 |
|---|---|---|
| 简历语义索引 | **已交付**：脱敏派生数据、与候选人生命周期同步、六节点流转日志；12 锚点评测 RRF+rerank recall@5=0.92 / MRR=0.785 | Screening/Sourcing 的证据来源 |
| 企业知识库 | MaxKB 本职能力，工作区既有知识库**直接复用，不新建**；HrConfig 配置 Agent 可用的 KB 白名单 | JD 模板/职级标准、面试题库、政策与 FAQ |
| 职位库 | 不建向量库（试点规模 500 职位）；SQL 相似（部门/城市/技能重叠）+ `HIRED` 关联聚合画像 | JD 对标、初筛参考 |

**数据边界重申（继承 PRD §1/§6）**：候选人数据永不写入企业知识库；`search_knowledge` 只读；简历语义索引仅存可重建的脱敏派生数据。前置整改：简历语义索引已通过 hr_protected 标记与企业知识库目录隔离，删除和编辑接口会拒绝受保护索引；后续变更必须保持该保护。

**对 RAG 链路的范围约束**：当前 `search_resumes` 支持可选 `candidate_id/document_ids` 和 resume_database_ids 召回范围参数；查询理解、双路召回、RRF、rerank、Small-to-Big、降级链与评测口径均不变。未传范围参数时行为与 C 阶段交付一致。

## 8. 数据模型增量

新增两张表（均挂 `workspace_id`，入库迁移 + 测试）：

**`hr_agent_run`**：字段见 §4.3。

**`hr_agent_proposal`**：

| 字段 | 说明 |
|---|---|
| run FK | 溯源到运行账本 |
| target_type / target_id | APPLICATION / JOB / INTERVIEW |
| action | ADVANCE / DECLINE / HOLD / DRAFT（Screening 的 ADVANCE/DECLINE/HOLD 由服务端派生，LLM 不可自报） |
| payload_json | §6.2 结构 |
| status | `PENDING → ACCEPTED / DISMISSED / EXPIRED`（状态机服务端强制） |
| decided_by / decided_at / decision_note | 审批人与备注（= 人工反馈闭环的数据源） |

**既有模型扩展**：

- `HrAuditAction`（`apps/hr/models/recruitment.py:380`）新增：`AGENT_RUN`、`AGENT_DECIDE`；
- `HrConfig` 新增：`agent_enable_screening`（默认关）、`agent_score_bands`（JSON，§6.3 默认值）、`agent_score_version`、`agent_knowledge_bases`（KB 白名单 id 列表）、`agent_max_concurrent_runs`（默认 2）、`agent_run_rate_limit`（默认 10 次/工作区/小时）、`agent_prompt_versions`（只读记录生效版本）。

**反馈闭环**：`decision + decision_note` 即 PRD §9.2 C 阶段「人工反馈」的落地形态——按 agent_type × 分数带统计采纳率，用于标定阈值与迭代提示词；采纳率报表进 dashboard。

## 9. 权限、PII 与合规

- **Agent 数据可见性 = 触发者资格**：人工触发的 run 按触发者 HR 资格过滤（VIEWER 触发的 Copilot 只见脱敏数据）；事件触发的 run 按工作区 OPERATOR 口径**只读**，写仅 Proposal。工具层复用服务端权限校验，不另开旁路。
- **LLM 上下文投影优先于角色明文**：无论触发者是 VIEWER 还是 OPERATOR/ADMIN，进入模型的工具结果一律经 §4.2 `to_llm_context()` 投影，**不包含明文联系方式、备注、简历原文**。
- **Proposal 审批权限**：VIEWER 可查看脱敏提案但不可决策；决策要求 OPERATOR+，且操作者为关联 `owner_id` 或 ADMIN。
- **面试官侧**：Interview Copilot 产物仅含最小可见信息（本人相关 + 无 PII），沿用 A3 面试协作口径。
- **不留 PII 痕迹**：`tool_trace`/`input_meta`/日志遵守既有脱敏规则（手机号/邮箱/简历原文不入普通日志）；报告证据摘录来自脱敏 chunk。
- **LLM 外发内容** = 脱敏 chunk + 结构化字段 + 职位信息，与 PRD §6「默认不发送联系方式、备注、简历原文」一致；`HrAgentRun` 记录租户/模型/数据类别/用途/失败，履行 §6 义务。
- **审计**：AGENT_RUN / AGENT_DECIDE 入 HrAuditLog（只增不改）；当前已通过 trace_id 关联 Agent run、Proposal 决策与业务审计；后续新增 Agent 必须继续写入该链路标识。

## 10. 评测与验收

| 层 | 指标 | 基线 / 目标 |
|---|---|---|
| 检索层（已达成） | 12 锚点 recall@5 | RRF+rerank = 0.92（沿用，不重考） |
| 模型能力 | SenseNova function calling 探针 | D1 第 0 步通过；否则启用 §4.1 固定顺序降级 |
| 初筛一致性 | 预注册验收集 ≥ 200 例；阈值只在独立标定集（≥ 80 例，或 5 折交叉验证）上调，验收集只跑一次 | 分带报告；整体 ≥ 80%，附置信区间 |
| 引用忠实度 | 抽检 evidence 真支撑对应维度结论的比例 | ≥ 95% |
| 时延 | 单份初筛端到端 | 异步 P95 ≤ 30s，不阻塞任何业务请求 |
| 降级 | 模型不可用 | run FAILED（重试 2 次），人工流程零阻塞，有自动化测试 |
| 试点观测 | 建议采纳率、初筛处理时长对比 | D1 试点期采集，作为阈值固化与 D3 开放免审的依据 |

每阶段沿用当前仓库测试/验收流程：状态机、权限、PII、降级必须有自动化测试（对齐 PRD §8 口径）。

## 11. 前端改动（概要）

| 页面/组件 | 当前实现 |
|---|---|
| 职位页申请卡与 AI 抽屉（D1） | Screening 建议徽标、评分维度、证据、风险、Proposal 操作；支持在 ACTIVE 简历库中选择证据范围；未选择时保持全库行为 |
| 职位页 JD / Sourcing / 沟通区域（D2/D3） | JD 草稿采纳、沉睡候选人激活清单、拒绝/推进/FAQ 等沟通草稿；外发仍由人工完成 |
| my-interviews（D2） | Interview Copilot 面试问题和评估草稿；面试反馈仍由人工提交 |
| dashboard 与 AI 设置 | Agent 运行/采纳率统计、模型配置、企业知识库白名单、Screening 开关和运行限制 |
| Proposal 列表与审计 | Application、Job、Interview Proposal 列表，以及 AGENT_RUN/AGENT_DECIDE 审计记录 |
| 独立 Agent 工作台（D4 首版） | 已实现：统一运行记录、工具轨迹、失败/跳过重试、Token 明细、Proposal 收件箱、证据链、Screening/Sourcing 简历库范围选择；后续继续补跨页指标汇总、原文定位和反馈重试表单 |

## 12. 路线图（增补 PRD §9.2「D 阶段」）

| 阶段 | 范围 | 完成定义 |
|---|---|---|
| **D1：运行时底座 + Screening v1** | 工具调用能力探针与降级方案、agents 包（触发器/Runner/工具注册表/幂等降级/成本护栏）、`search_resumes` 可选文档集限定参数、`hr_agent_run`/`hr_agent_proposal`、服务端评分与提案权限、HrConfig 扩展、语义索引保护整改、前端报告卡、预注册评测集与一致性报告 | 初筛建议与人工一致率 ≥ 80%（≥200 例验收集，阈值经独立标定集/交叉验证冻结）；引用忠实度 ≥ 95%；候选人文档限定与 PII 投影有自动化测试；降级零阻塞有测试；agent 开关默认关，试点工作区灰度开启 |
| **D2：JD 起草 + Interview Copilot** | 企业知识库工具接入、两 Agent、前端草稿 UI | JD 草稿采纳率与面试问题可用性试点报告；面试官侧无 PII 泄露验证 |
| **D3：Sourcing + 沟通草稿 + 免审配置** | 人才库激活清单、话术草稿、反馈闭环标定 | 采纳率报表进 dashboard；免审分带（若有）经一致性数据论证后由 ADMIN 显式开启，保留审计与人工回滚 |
| **D4：Agent 工作台** | 独立 Agent 页面、运行记录、工具轨迹、失败/跳过重试、Token 明细、Proposal 收件箱、证据链和 Screening/Sourcing 简历库范围选择 | **首版已实现**；后续补跨页指标、原文定位和 Interview feedback 重试输入；不改变现有 Propose → Confirm → Execute 业务约束 |

## 13. 与外部参考架构的差异裁决

| 参考方案 | 本项目决策 | 理由 |
|---|---|---|
| LangGraph / FastAPI 编排 | **不用**。Django 服务 + Celery + 信号，Agent 为 `apps/hr/agents/` 包 | 单体已具备异步/防重/定时/审计基础设施；MaxKB flow 引擎已物理删除，不回引；避免双运行时 |
| 简历/职位/企业三个向量知识库 | 简历索引复用既有；**企业知识库直接复用 MaxKB 工作区知识库**；职位库用 SQL 相似，不建向量库 | 企业知识库是本产品内核本职（相对参考架构的天然优势）；500 职位量级不值得向量库 |
| 硬条件不满足**自动拒**、高分**自动推进** | 一律降级为**建议**，人工确认后走 ATS v2 状态机命令；免审仅在 D3 经数据论证后按分带开放 | 兼容 PRD §2.2「人工决策优先」；保留全自动的演进路径而非一次性放开 |
| Scheduling Agent、候选人端邮件/IM 外发 | 边界外 | 内部工作台定位、无渠道集成、与数据边界冲突 |
| `agent_run` + `feedback` 两表 | 增加 **Proposal 一等工件**（参考架构缺失「提议」实体，审批无对象可挂） | 审批、过期、采纳率统计都需要独立工件；feedback 并入 decision 字段 |
| Milvus/ES、Docling、多模型路由 | 均不引入；pgvector+tsvector、docx/txt 规则+LLM 切片、单 LLM 起步 | 检索已达标（0.92）且 10k 规模远未到瓶颈；模型分级待 D1 评测不达标再议（run 表已记 token 成本） |

## 14. 风险与前置整改

| # | 项 | 处置 |
|---|---|---|
| 1 | `api.txt` 中为 SenseNova/SiliconFlow 测试 Key | 文件已在 `.gitignore` 且未纳入 Git；保持本地测试使用即可，正式上线/评测前替换为正式 Key 并统一走环境变量 |
| 2 | HrAuditLog trace_id 已实现 | AGENT_RUN / AGENT_DECIDE 必须持续写入 run 或 proposal.run_id，禁止新增无链路审计 |
| 3 | 简历语义索引保护 | 已通过 hr_protected 标记、目录过滤和删除/编辑守卫完成；后续改动必须保持保护 |
| 4 | 单一 flash-lite 模型承担评估，能力上限与工具调用支持均未知 | D1 第 0 步先做 function calling 探针与评估质量试点；不达标则按 §4.1 降级或评估档引入强模型（Provider 已是 OpenAI 兼容，接入成本低） |
| 5 | 分数带阈值（80/60）未经标定 | D1 交付物：用独立标定集/交叉验证标定后冻结，再在预注册验收集上只跑一次 |
| 6 | 灌库语料 skills 为空曾致结构化基线 0.00 | 沿用 `backfill_candidate_skills` 回填；评测集语料须先回填 |
| 7 | 初筛语义证据可能跨候选人召回 | 已裁决：`search_resumes` 增加候选人文档集限定（§4.2/§6.1），默认行为不变；D1 必须覆盖自动测试 |
