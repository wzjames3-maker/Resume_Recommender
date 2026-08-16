# 传统 ATS 开源项目调研（可直接抄的底座）

> 调研日期：2026-08-16。方法：GitHub 检索并浅克隆实际仓库，读 schema / 业务层 / 路线图，不依赖二手介绍。
> 结论：**底座抄 Harly 的数据模型与交互原则，流程账本抄 OpenCATS 的 candidate_joborder + status_history + activity；Nueno 仅保留表单模板概念；YAWIK 仅作术语对照，不采用。**

## 1. 实际查看的项目

| 项目 | Stars | 许可证 | 形态 | 价值判断 |
|---|---|---|---|---|
| `Vytral/harly` | ~2 | MIT | Next.js + Drizzle + PostgreSQL，现代自托管 ATS | **主要抄它**：Application 为一等对象、JobStage 可配置、StageHistory、Offer/Interview/Scorecard 挂 Application、AI copilot 的 propose-confirm-execute 与 AiActionReceipt |
| `opencats/OpenCATS` | ~728 | MPL-2.0 | PHP 传统招聘 CRM/ATS | **抄它的账本模式**：`candidate_joborder`、`candidate_joborder_status_history`、`activity`、`saved_list`、`joborder.owner/recruiter` |
| `nueno-co/nueno` | ~265 | AGPL-3.0 | Next.js + Prisma | 仅借鉴「职位自定义申请表单字段」的思路；代码因 AGPL 不直接抄 |
| `cross-solution/YAWIK` | ~131 | MIT | PHP ZF ATS/Jobboard | 仅用于术语与模块划分对照，不采用其技术栈 |

## 2. 直接采用的 Harly 设计（MIT）

1. **Application 是产品一等对象**：`Candidate + Job + currentStage + status`。UI 围绕“某人在某职位的进展”，而不是围绕三个平级模块。
2. **每个 Job 拥有自己的 Pipeline**：
   - `job_stages(id, workspace_id, job_id, name, color, order)`
   - 唯一约束 `(job_id, order)`、`(job_id, name)`
   - 应用停在 `applications.current_stage_id`；每次移动写 `application_stage_history(from_stage_id, to_stage_id, moved_by_id, created_at)`
3. **终态与阶段分离**：
   - `application_status ∈ active / hired / rejected / withdrawn`
   - Stage 是可配置过程，Status 是结果；避免我们用一个大枚举同时表达“进行中阶段”和“终态”导致状态机膨胀。
4. **子对象挂 Application，并带复合一致性外键**：Interview / Offer / Scorecard / Evaluation 同时冗余 `(workspace_id, application_id, candidate_id, job_id)`，防止跨工作区或串对象。
5. **AI Copilot 原则（照抄其产品原则）**：
   - Context before verbosity：当前页面实体显式传入；
   - Evidence before confidence：推荐必须引用真实简历/申请/评分/面试/备注；
   - Propose → Confirm → Execute：AI 不得静默移动、拒绝、发信、排面试；
   - Backend-enforced safety：权限、workspace、schema、幂等、事务由后端强制；
   - Recoverable by default：外部失败不丢本地 ATS 记录，可重试。
6. **AI 数据表形态（照抄字段思想）**：
   - `ai_evaluations`：rubric snapshot、criteria evidence、score、recommendation、requires_human_review、used_resume、engine/version；
   - `ai_action_receipts`：toolName、requestHash、status、result、expiresAt，唯一 `(workspace, actionId)`；
   - `ai_conversations/ai_messages`：按 candidate 级联删除，避免候选人擦除后残留 PII 对话；
   - `ai_usage_events`：每次模型调用 token 账本。

## 3. 直接采用的 OpenCATS 设计（MPL-2.0，只抄结构不抄代码）

1. **候选人与职位是多对多关系，关系表承载流程**：`candidate_joborder(candidate_id, joborder_id, status, date_submitted, rating_value, added_by)`。
2. **状态字典与历史分离**：
   - 状态字典可维护（`can_be_scheduled`、`triggers_email`）；
   - 每次流转写 `candidate_joborder_status_history(status_from, status_to, date)`，这是审计/漏斗/周期统计的数据源。
3. **统一 Activity 时间线**：`activity(data_item_type, data_item_id, joborder_id, type, notes, entered_by, date_occurred)`，把电话/邮件/会议/状态变更都放在同一条候选人时间线。
4. **JobOrder 的招聘责任制**：`owner`、`recruiter`、`entered_by` 分开；我们保留 `owner_id` 并新增 `recruiter_id`（默认 owner）。
5. **Saved List / Pipeline 批量操作**：搜索结果加入名单、名单批量进入职位，作为 Agent “Sourcing 清单” 的落点。

## 4. 与本项目结合方式

- **底座**：把当前 `CandidateAssignment` 重构为 Harly 式 `Application + JobStage + ApplicationStageHistory`；
- **RAG**：`search_resumes` 继续作为只读工具，返回候选证据与命中段落；不改召回/精排链路；
- **Agent**：Harly AI copilot 的 propose-confirm-execute + OpenCATS 的完整 history/activity 账本 + 我们已设计的 `HrAgentProposal`。
