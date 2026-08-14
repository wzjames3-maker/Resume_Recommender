# 招聘流程模型完善设计（A2）

## 目标

补齐 PRD 第 4、5 节定义的招聘流程模型，为后续权限、审计、生命周期（A3/A4）提供数据基础：职位支持暂停/关闭原因与负责人，职位关联支持渠道、关系类型、负责人、终止原因与 `WITHDRAWN`，服务端强制执行状态迁移矩阵、重新投递与误拒绝恢复规则，关闭职位可批量收尾在途关联。

## 范围

### 范围内

- `Job`：新增状态 `DRAFT`、`ON_HOLD`；新增 `close_reason`（枚举）与 `owner_id`（负责人）。
- `CandidateAssignment`：新增状态 `WITHDRAWN`；新增 `relation_type`、`channel`、`applied_at`、`owner_id`、`termination_reason`（枚举）与 `is_reapply`。
- 状态迁移矩阵服务端校验（含 `REJECTED → PENDING_SCREEN` 管理员恢复）。
- 重新投递：存在同 `(candidate, job)` 终态历史时，新建关联自动标记 `is_reapply`。
- 关闭职位：管理员关闭时对在途关联做有原因的批量收尾（置 `CLOSED`）。
- 前端：职位状态下拉与关闭原因、负责人选择、指派渠道/关系类型、状态变更原因输入、按负责人筛选的「待我处理」入口。

### 不在范围内

- HR 显式授权角色与脱敏（A3）。
- 审计事件表（A3）。
- 数据来源/告知元数据、删除/匿名化与简历 TTL（A4）。
- 面试官与负责人身份绑定校验（A3 随授权统一处理）。

## 数据模型

### JobStatus 扩展

```
DRAFT / OPEN / ON_HOLD / CLOSED
```

- `DRAFT`：仅负责人与管理员可编辑，不能建立职位关联。
- `OPEN`：可以建立新的职位关联。
- `ON_HOLD`：保留历史和在途记录，不能建立新关联。
- `CLOSED`：结束；必须记录 `close_reason`。

### Job 新增字段

| 字段 | 类型 | 规则 |
|---|---|---|
| `close_reason` | CharField(20)，choices | `FILLED`（招满）、`CANCELLED`（取消）、`DUPLICATE`（重复需求）、`OTHER`（其他），可空。 |
| `owner_id` | UUIDField(null=True, blank=True) | 职位负责人，创建时默认当前用户。 |

### AssignmentStatus 扩展

```
PENDING_SCREEN / SCREEN_PASSED / INTERVIEWING / OFFER / HIRED / REJECTED / WITHDRAWN / CLOSED
```

- 有效状态集合不变（`PENDING_SCREEN`、`SCREEN_PASSED`、`INTERVIEWING`、`OFFER`）。
- `WITHDRAWN` 为终态（候选人主动退出或无法继续联系）。

### CandidateAssignment 新增字段

| 字段 | 类型 | 规则 |
|---|---|---|
| `relation_type` | CharField(16)，choices | `APPLY`（候选人投递）、`SEEK`（主动寻访）、`REFERRAL`（内推）、`HEADHUNTER`（猎头推荐），默认 `APPLY`。 |
| `channel` | CharField(20)，choices | 复用 `ResumeChannel` 枚举（`REFERRAL`/`JOB_SITE`/`HEADHUNTER`/`CAMPUS`/`OTHER`），默认 `OTHER`。 |
| `applied_at` | DateTimeField(default=now) | 进入日期；重新投递时可覆盖。 |
| `owner_id` | UUIDField(null=True, blank=True) | 当前负责人，创建时默认当前用户。 |
| `termination_reason` | CharField(20)，choices | 终态必填：`NOT_FIT`（不合适）、`SALARY`（薪资不符）、`UNREACHABLE`（无法联系）、`CANDIDATE_WITHDRAW`（候选人退出）、`JOB_CLOSED`（职位关闭）、`MERGED`（合并）、`OTHER`（其他）。 |
| `is_reapply` | BooleanField(default=False) | 是否为重新投递/重新激活记录。 |

## 状态机规则

| 源状态 | 允许目标状态 | 附加规则 |
|---|---|---|
| `PENDING_SCREEN` | `SCREEN_PASSED`、`REJECTED`、`WITHDRAWN`、`CLOSED` | 进入终态必填 `termination_reason`。 |
| `SCREEN_PASSED` | `INTERVIEWING`、`REJECTED`、`WITHDRAWN`、`CLOSED` | 同左。 |
| `INTERVIEWING` | `OFFER`、`REJECTED`、`WITHDRAWN`、`CLOSED` | 面试反馈不自动流转。 |
| `OFFER` | `HIRED`、`REJECTED`、`WITHDRAWN`、`CLOSED` | 进入 `HIRED` 前须已有 `OFFER` 接受结论（前端录入备注，不强制字段）。 |
| `REJECTED` | `PENDING_SCREEN` | 仅工作区管理员，必填恢复原因（记录到 `note`，格式 `[restore] <原因>`）。 |
| `WITHDRAWN` / `CLOSED` / `HIRED` | 无 | 不恢复原关联；按重新投递或离职后新建规则处理。 |

- 非法流转返回 400，消息含当前状态与目标状态。
- 终态流转（`REJECTED`/`WITHDRAWN`/`CLOSED`）必须携带 `termination_reason`，否则 400。
- 位置状态校验：创建关联时职位须 `OPEN`（`DRAFT`/`ON_HOLD`/`CLOSED` 均拒绝）；`ON_HOLD`/`CLOSED` 职位下的现有在途关联仍可流转到终态，但不能流转到 `INTERVIEWING`/`OFFER`/`HIRED`。
- 重新投递：创建关联时若该 `(workspace_id, candidate, job)` 存在任一终态（`REJECTED`/`WITHDRAWN`/`CLOSED`）历史记录，则 `is_reapply=True`。
- 误拒绝恢复后，同一 `(candidate, job)` 若仍存在其他有效关联则拒绝恢复（保持唯一约束语义）。

## API

统一前缀：`/admin/api/workspace/{workspace_id}/hr`。权限沿用当前（成员可操作职位关联，管理员可建/改职位）。

| 方法 | 路径 | 用途 |
|---|---|---|
| PUT | `/jobs/{job_id}` | 支持 `status`、`owner_id`、`close_reason` 更新（关闭走专用接口）。 |
| PUT | `/jobs/{job_id}/close` | 关闭职位：`close_reason` 必填；该职位所有有效关联批量置 `CLOSED`（`termination_reason=JOB_CLOSED`），返回被收尾数量。 |
| PUT | `/jobs/{job_id}/reopen` | 恢复招聘：`ON_HOLD`/`CLOSED` → `OPEN`，清空 `close_reason`（仅管理员）。 |
| POST | `/jobs/{job_id}/assignments` | 新建关联：支持 `relation_type`、`channel`、`applied_at`、`owner_id`。 |
| PUT | `/assignments/{assignment_id}` | 状态流转与备注：支持 `status`、`termination_reason`、`owner_id`、`note` 更新。 |
| GET | `/assignments` | 关联列表（按候选人/职位）支持 `owner_id` 筛选。 |
| GET | `/candidates` | 候选人列表支持 `owner_id`（有该负责人关联）筛选。 |

跨工作区一律 404。`close_reason`/`termination_reason` 非法枚举值 400。

## 前端

- 职位表单：状态下拉 `草稿/开放/暂停/关闭`；关闭时必填原因选择；负责人选择（调用内核 `GET /admin/api/workspace/{id}/member`，展示成员姓名，存 `user_id`）。
- 职位操作：关闭/恢复按钮（关闭弹窗带原因，展示将被收尾的在途关联数）。
- 指派/候选人行：渠道、关系类型、负责人展示与编辑；状态流转弹窗在进入终态时必填终止原因。
- 「待我处理」入口：候选人页与职位页新增按 `owner_id=当前用户` 筛选的快捷视图。

## 测试

- 迁移矩阵：每行允许/禁止流转各一例；终态缺 `termination_reason` 返回 400。
- `REJECTED → PENDING_SCREEN` 仅管理员；成员调用 403；恢复后 `termination_reason` 清空。
- 重新投递：`REJECTED` 后再创建关联 `is_reapply=True`，`applied_at` 可覆盖。
- 关闭职位：`close_reason` 缺失 400；关闭后有效关联批量 `CLOSED` 且 `termination_reason=JOB_CLOSED`；`DRAFT`/`ON_HOLD` 职位不能建新关联；`ON_HOLD` 下不能流转到 `INTERVIEWING`。
- 负责人：创建默认当前用户；可按 `owner_id` 筛选。
- 非法枚举（`close_reason`/`relation_type`/`channel`/`termination_reason`）400。
- 跨工作区 404。

## 验收

HR 全量测试 PASS、`manage.py check` 无问题、`makemigrations --check --dry-run` 无漂移、前端 `vue-tsc` 与 admin/chat 双构建 PASS。

## 取舍

- 负责人暂存 `user_id`（UUID），不建外键不做成员校验：A3 授权时统一校验归属，避免本期引入成员查询依赖。
- 终止/关闭原因使用枚举而非自由文本：保证统计口径；详情通过备注补充。
- 恢复操作记录到 `note` 而非独立字段：避免为单一操作新增字段，A3 审计表统一承接操作记录。
- 面试官仍为文本字段：与四期保持一致，A3 不扩大范围。
