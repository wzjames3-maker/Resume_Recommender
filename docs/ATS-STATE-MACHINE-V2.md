# ATS v2 目标设计（传统 ATS 底座 + RAG + Agent）

> 文档状态：目标设计基线，2026-08-16。
> 本文件取代当前 `CandidateAssignment` 固定状态机，作为 ATS 重构与 D 阶段 Agent 的共同前置。
> 参考依据：`docs/ATS-OPENSOURCE-REFERENCE.md`（已实际查看 Harly / OpenCATS / Nueno / YAWIK）。
> 权威顺序（目标态）：**本文件 > PRD.md（产品意图） > PRD-AGENT-RAG.md（Agent 层）**；`docs/ATS-DESIGN-SPEC.md` 降级为现状代码记录，仅用于迁移对照。

## 0. 一句话结论

把当前「CandidateAssignment 一个字段塞下所有阶段和终态」的模型，换成传统 ATS 的通用结构：

```text
Candidate ——< Application >—— Job
                 │
                 ├── current_stage_id → JobStage（可配置 Pipeline）
                 ├── status → ACTIVE / HIRED / REJECTED / WITHDRAWN / CLOSED
                 └── StageHistory / Events（不可变账本）
```

- **阶段**是可配置的“进行到哪一步”；
- **状态**是“最终结果是什么”；
- **Agent**只读 RAG、写 Proposal，人确认后调用 Application 命令。

## 1. 核心对象

### 1.1 Job + JobStage（抄 Harly）

| 字段 | 说明 |
|---|---|
| Job | 保留现有 `DRAFT/OPEN/ON_HOLD/CLOSED` 职位生命周期；新增 `recruiter_id`（默认 owner） |
| `hr_job_stage` | `workspace_id`、`job_id`、`key`、`name`、`color`、`order`、`is_system` |
| 默认模板 | `APPLIED 待筛选` → `SCREEN 初筛` → `INTERVIEW 面试` → `OFFER Offer`；每个 Job 创建时复制一份，可按职位裁剪/改名 |
| 约束 | 唯一 `(job_id, order)`、`(job_id, key)`、`(job_id, name)` |

### 1.2 Application（重命名 CandidateAssignment，抄 Harly + OpenCATS）

| 字段 | 说明 |
|---|---|
| candidate / job / workspace_id | 复合一致性外键；候选人与职位可有多条历史 Application |
| `current_stage_id` | 当前阶段，FK 到 JobStage；终态时保留最后阶段 |
| `status` | `ACTIVE`（活跃）/ `HIRED` / `REJECTED` / `WITHDRAWN` / `CLOSED` |
| `relation_type` / `channel` / `channel_detail` / `applied_at` | 来源与渠道，沿用现有语义 |
| `owner_id` / `recruiter_id` | 当前负责人 / 招聘顾问，默认均为创建人 |
| `termination_reason` / `terminated_at` | 进入终态原因与时间；适配矩阵见 §2.3 |
| `reapply_of_id` / `reapply_no` | 重新投递时指向上一历史 Application |
| `rehire_confirmed` / `rehire_reason` | 候选人存在 HIRED 历史后再次创建 Application 的 ADMIN 确认 |

**唯一约束**：
- 部分唯一：同 `(workspace, candidate, job)` 至多一条 `status=ACTIVE` 的 Application；
- 历史终态 Application 可保留多条，`reapply_no` 递增。

### 1.3 账本（抄 OpenCATS）

| 表 | 说明 |
|---|---|
| `hr_application_event` | `event_type`、`from_stage_id/to_stage_id`、`from_status/to_status`、`actor_id`、`reason_code`、`reason_text`、`idempotency_key`、`trace_id`、`create_time` |
| `hr_activity` | 电话/邮件/会议/备注/状态变更统一时间线，挂在 Candidate 或 Application 上 |
| `hr_saved_list` / `hr_saved_list_entry` | 搜索/Agent Sourcing 结果暂存名单，再批量进入职位 |

## 2. 阶段与状态规则

### 2.1 Application 状态机

| 迁移 | 角色 | 守卫 |
|---|---|---|
| 创建 | OPERATOR+ | 候选人 ACTIVE；Job OPEN；同候选同职位无 ACTIVE Application；候选人存在 HIRED 历史时 ADMIN + `rehire_confirmed=true` |
| ACTIVE 内移动阶段 | OPERATOR+ | 目标 Stage 属于同一 Job；目标 stage 不可为系统终态；跨 stage 跳级需 ADMIN 确认 |
| → REJECTED | OPERATOR+ | 原因 `NOT_FIT / SALARY / OTHER`；源为 OFFER 阶段且有 SENT Offer 时先处理 Offer |
| → WITHDRAWN | OPERATOR+ | 原因 `CANDIDATE_WITHDRAW / UNREACHABLE / OTHER`；同上 |
| → CLOSED | OPERATOR+ | 原因 `JOB_CLOSED / MERGED / OTHER`；`JOB_CLOSED` 仅由 Job 关闭联动 |
| → HIRED | 系统 | 仅由 Accepted Offer 同事务触发 |
| REJECTED → ACTIVE | ADMIN | 仅误拒绝恢复；恢复原因必填；无其他 ACTIVE Application |
| WITHDRAWN / CLOSED / HIRED | 无 | 不恢复；重新参与 = 新建 Application + `reapply_of_id` |

### 2.2 Stage 移动规则

- 默认只允许按 `order` 前移一位；后退/跳级必须 ADMIN 或 owner，且写 `reason_text`。
- 每次移动写一条 `hr_application_event`（from/to stage），无论是否改 status。
- 终态 Application 的 `current_stage_id` 保留在最后阶段，不再允许移动。
- Job 创建时生成默认四阶段；已有 Job 迁移时按当前固定状态映射生成对应 Stage。

### 2.3 终止原因 × 终态

| 终态 | 允许原因 |
|---|---|
| REJECTED | NOT_FIT / SALARY / OTHER |
| WITHDRAWN | CANDIDATE_WITHDRAW / UNREACHABLE / OTHER |
| CLOSED | JOB_CLOSED / MERGED / OTHER |
| HIRED | 无（由 Offer accept 决定） |

## 3. 子对象守卫

### 3.1 Interview

- 仅 `ACTIVE` 且当前 Stage 为 `SCREEN` 或 `INTERVIEW` 时可创建；
- `round_no` 服务端生成，唯一 `(workspace, application_id, round_no)`；
- 面试反馈仅本人；反馈结果 `PASSED/FAILED/NO_SHOW/CANCELLED`；
- 面试永远不自动改 Application 状态。

### 3.2 Offer

- 创建：Application 当前 Stage 为 `OFFER`，且无 `DRAFT/SENT` 活跃 Offer；
- 发送：`approval_status=APPROVED`，同 Application 至多一条 SENT；
- 接受：同一事务写 Offer=ACCEPTED + Application→HIRED + 幂等 Handoff；
- 拒绝/撤回：Offer 终态，Application 停留 OFFER Stage；
- 附件只在 DRAFT 可变更。

### 3.3 Job 关闭

- `CLOSE_JOB` 先返回活跃 Application 数预览；
- `STRICT`：必须 0 条 ACTIVE；
- `BULK`：显式确认后逐条写事件并置 Application=CLOSED + JOB_CLOSED，存在 DRAFT/SENT Offer 时先系统 WITHDRAW Offer。

## 4. RAG 接入方式（不改检索链路）

- `search_resumes(query, candidate_id=None, document_ids=None)` 继续作为 Agent 只读工具；
- 检索默认全库，给候选人评估时必须限定到该候选人的 `document_ids`；
- 双路召回、RRF、rerank、Small-to-Big、降级链、评测口径保持不变；
- 企业知识库作为 JD 模板、面试题库、政策 FAQ 的只读来源。

## 5. Agent 接入方式（抄 Harly AI Copilot 原则）

### 5.1 原则

1. Context before verbosity：触发时显式传 `workspace + application + candidate + job`；
2. Evidence before confidence：每个结论必须引用 RAG 脱敏 chunk 或结构化字段；
3. Propose → Confirm → Execute：Agent 只写 Proposal；人工确认后调 Application 命令；
4. Backend-enforced safety：权限、workspace、schema、幂等、事务在后端强制；
5. Recoverable by default：AI/外部模型失败不影响人工 ATS 流程。

### 5.2 落点

| Agent 输出 | 落表 | 人工确认后调用 |
|---|---|---|
| 初筛评估 + ADVANCE | `HrAgentProposal` | `move_stage(SCREEN)` 或对应下一 Stage |
| 初筛评估 + DECLINE | `HrAgentProposal` | `reject_application(NOT_FIT)` |
| JD 草稿 | `HrAgentProposal(action=DRAFT)` | 仅采纳文本，不改状态 |
| Sourcing 清单 | `hr_saved_list_entry` | 批量创建 Application |

### 5.3 应抄 Harly 的 AI 数据表

- `hr_agent_run` ≈ Harly `ai_usage_events + conversation/run`：模型、token、tool_trace、输入摘要；
- `hr_agent_proposal` ≈ Harly `ai_action_receipts + ai_evaluations.recommendation`：唯一 action id、request hash、expires、decision；
- 候选人删除时，级联清理与该候选人相关的 Agent 对话/PII 派生数据。

## 6. API 面（目标）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/hr/jobs/{job_id}/stages` | 创建/调整 Job Stage |
| POST | `/hr/jobs/{job_id}/applications` | 创建 Application |
| POST | `/hr/applications/{id}/move-stage` | `{to_stage_id, reason, idempotency_key}` |
| POST | `/hr/applications/{id}/reject` / `/withdraw` / `/close` | 终态命令 |
| POST | `/hr/applications/{id}/restore` | ADMIN 恢复误拒绝 |
| GET | `/hr/applications/page/{page}/{size}` | 队列（owner/status/stage/job/channel/city/q） |
| GET | `/hr/applications/{id}/events` | 阶段与状态事件时间线 |
| POST | `/hr/jobs/{job_id}/close` | `{close_reason, mode: STRICT|BULK, bulk_confirmed}` |
| POST | `/hr/agents/{type}/run` | Agent 运行 |
| POST | `/hr/proposals/{id}/accept` / `/dismiss` | Proposal 审批 |

旧 `PUT /assignments/{id}` 兼容期仅允许 `owner_id/note`；带 status 一律 400 并指向新命令端点。

## 7. 从当前代码迁移

1. 数据迁移：
   - `CandidateAssignment` → `Application`：当前 `status` 映射为 Stage + Status 两段；
   - 当前固定状态映射为每个 Job 的默认 Stage 模板；
   - 生成 `hr_application_event` 的 `IMPORTED` 锚点事件；
2. `Interview/Offer/Handoff` 外键从 assignment 切到 application，增加复合一致性外键；
3. 前端 Pipeline 看板改为读取 JobStage，不再硬编码六列；
4. 旧测试按新命令 API 重写；全量回归、`makemigrations --check`、`migrate --check`。

## 8. 验收

- 每个命令的守卫、角色、原因矩阵、幂等有自动化测试；
- 同 candidate+job 并发创建只允许一条 ACTIVE Application；
- Stage 移动/终态每次都产生事件；同 idempotency_key 不重复；
- Offer 未审批不能 SENT；同 Application 只允许一条 DRAFT/SENT；
- Job 关闭 STRICT/BULK 行为与事件完整；
- Agent Proposal 接受后只通过命令端点改状态，审计操作者=审批人；
- 现有 RAG 检索评测不回退（recall@5=0.92 基线不变）。
