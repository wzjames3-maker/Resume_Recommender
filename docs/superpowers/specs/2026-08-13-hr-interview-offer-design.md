# 面试与 Offer 流转设计

## 目标

在 `apps/hr` 交付招聘流程的面试与 Offer 阶段：扩展指派状态机（面试中、Offer、已入职），支持面试轮次安排、结果与反馈记录，以及入职后对候选人的再指派限制。流程审计通过既有指派状态与时间字段覆盖，不新增审计表。

## 范围

### 范围内

- 指派状态扩展：新增 `INTERVIEWING`、`OFFER`、`HIRED` 三个状态。
- 有效状态集合更新：`PENDING_SCREEN`、`SCREEN_PASSED`、`INTERVIEWING`、`OFFER` 视为有效指派（唯一约束、归档校验、重新激活校验同步）。
- 面试记录：每个指派可有多轮面试，记录轮次、面试官、面试时间、结果与反馈。
- 状态机合法流转校验：`SCREEN_PASSED → INTERVIEWING → OFFER → HIRED`；任意有效状态可进入终态 `REJECTED` / `CLOSED`。
- 候选人存在 `HIRED` 指派时禁止再创建新指派。
- 前端：职位展开区候选人行支持状态流转；面试安排弹窗与面试记录展示。

### 不在范围内

- 面试官权限差异（面试官仅作为文本字段）。
- Offer 附件、薪资谈判、入职表单与员工档案。
- 审计事件表与完整流程历史快照。
- 自动提醒与超时流转。

## 数据模型

### AssignmentStatus 扩展

```
PENDING_SCREEN / SCREEN_PASSED / INTERVIEWING / OFFER / HIRED / REJECTED / CLOSED
```

- 有效状态（进行中）：`PENDING_SCREEN`、`SCREEN_PASSED`、`INTERVIEWING`、`OFFER`。
- 终态：`REJECTED`、`CLOSED`、`HIRED`。
- 条件唯一约束更新：同一 `(workspace_id, candidate, job)` 最多一条状态为有效状态的指派。
- `HIRED` 视为终态但候选人在库状态仍为 `ACTIVE`（仅禁止再创建新指派，不自动归档）。

### Interview

- UUID 主键与 `workspace_id`。
- `assignment` 外键（指向 `CandidateAssignment`）。
- `round_no` 轮次（正整数，从 1 开始）。
- `interviewer` 面试官姓名（文本，≤ 64 字符，可空）。
- `scheduled_at` 计划面试时间（可空）。
- `status` 面试结果，取值 `PENDING` / `PASSED` / `FAILED` / `NO_SHOW` / `CANCELLED`，默认 `PENDING`。
- `feedback` 反馈评语（文本，可空）。
- `user_id`、`create_time`、`update_time`。

## 状态机规则

| 当前状态 | 允许流转到 |
|---|---|
| PENDING_SCREEN | SCREEN_PASSED、REJECTED、CLOSED |
| SCREEN_PASSED | INTERVIEWING、REJECTED、CLOSED |
| INTERVIEWING | OFFER、REJECTED、CLOSED |
| OFFER | HIRED、REJECTED、CLOSED |
| HIRED / REJECTED / CLOSED | 无（终态） |

- 非法流转返回 400，消息含当前状态与目标状态。
- 面试通过（`PASSED`）不自动流转状态；由操作者显式流转到 `OFFER`。
- 指派进入 `HIRED` 后，该候选人不能再创建任何新指派（返回 400）。
- 关闭职位（`CLOSED`）后仍可流转现有指派到终态，但不能进入 `INTERVIEWING` / `OFFER` / `HIRED`（职位须 `OPEN`，沿用一期有效状态校验）。

## API

统一前缀：`/admin/api/workspace/{workspace_id}/hr`。权限沿用一期（成员可操作指派与面试）。

| 方法 | 路径 | 用途 |
|---|---|---|
| PUT | `/assignments/{assignment_id}` | 状态流转与备注（沿用一期，新增合法流转校验） |
| POST | `/assignments/{assignment_id}/interviews` | 安排面试（创建 PENDING 记录） |
| GET | `/assignments/{assignment_id}/interviews` | 面试记录列表（按轮次升序） |
| PUT | `/interviews/{interview_id}` | 更新面试结果、反馈、面试官、时间 |

请求与响应：

- 安排面试：`{"round_no": 1, "interviewer": "张伟", "scheduled_at": "2026-08-20T10:00:00Z"}`；`round_no` 缺省为当前最大轮次 + 1。
- 更新面试：`{"status": "PASSED", "feedback": "..."}`，允许部分字段。
- 指派流转沿用 `PUT /assignments/{id}` 的 `status` 字段。

跨工作区指派/面试一律 404。面试只能挂载当前工作区指派。

## 前端

- 职位展开区「候选人」标签：指派状态下拉增加「面试中」「Offer 中」「已入职」；候选人有 `HIRED` 指派时「加入职位」在匹配区域隐藏。
- 候选人行「面试」按钮打开面试抽屉：
  - 展示面试记录列表（轮次、面试官、时间、结果、反馈）。
  - 「安排面试」表单：面试官、面试时间、轮次（自动 +1）。
  - 每条记录可编辑结果与反馈（下拉：待面试/通过/未通过/未到场/取消）。
- 匹配候选人区域对已有 `HIRED` 指派候选人提示不可加入。

## 测试

后端测试至少覆盖：

- 合法流转链 `SCREEN_PASSED → INTERVIEWING → OFFER → HIRED` 全部通过。
- 非法流转（如 `PENDING_SCREEN → OFFER`、终态再流转）返回 400。
- 面试安排轮次自动 +1；更新结果与反馈。
- 候选人存在 `HIRED` 指派时创建新指派返回 400。
- 关闭职位后不能流转到 `INTERVIEWING` / `OFFER`。
- 跨工作区指派与面试返回 404。
- 有效指派唯一约束在新增有效状态下仍生效。

验收命令沿用前三期：HR 全量测试、Django 检查、迁移漂移检查、前端类型检查与双构建、裁剪端点产物扫描。

## 取舍

- 面试官为文本字段而非用户外键：避免权限模型复杂化，后续需要再迁移。
- 面试通过不自动流转状态：状态由操作者显式推进，流转规则简单可预期。
- `HIRED` 不自动归档候选人：保留候选人在库，仅禁止再指派；归档仍是独立操作。
- 不引入审计事件表：流转审计由指派状态与时间字段承担，符合当前数据规模。
