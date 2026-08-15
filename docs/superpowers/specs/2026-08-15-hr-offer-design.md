# Offer 工件设计（B2：独立实体、版本、审批、金额币种、发送/接受/拒绝/撤回、附件权限）

## 背景

PRD §4.5：OFFER 当前仅是流程状态，完整 Offer 能力需独立记录版本、审批、金额与币种、发送、接受、拒绝、撤回和附件权限，不得放入自由备注。PRD §5.3：通过面试的关联进入 OFFER，由具备权限的人员维护 Offer 工件和结论；Offer 接受后关联进入 HIRED。

## 范围

### 范围内

- Offer 独立实体：版本序列、审批状态、金额/币种、发送/接受/拒绝/撤回、附件（Offer letter）权限。
- 状态机：DRAFT → SENT → ACCEPTED / REJECTED / WITHDRAWN；仅 DRAFT 可编辑。
- 接受联动：Offer ACCEPTED 后指派自动流转 HIRED（事务内，写 ASSIGNMENT_TRANSITION 审计）。
- 拒绝不自动流转：候选人在 OFFER 状态的后续去向由 HR 按既有状态机手动处理。
- 附件权限：上传/删除 ADMIN；下载 OPERATOR/ADMIN（VIEWER 403，附件含敏感条款）。
- 审计：新动作 OFFER_SEND / OFFER_ACCEPT / OFFER_REJECT / OFFER_WITHDRAW / OFFER_APPROVE；创建/编辑复用 CREATE/UPDATE（object_type=OFFER）。

### 不在范围内

- 薪资谈判记录、Offer 模板渲染、候选人自助门户、电子签。
- 入职交接（B3，独立规格）。

## 数据模型

### Offer（db_table hr_offer）

| 字段 | 类型 | 规则 |
|---|---|---|
| workspace_id | CharField(64) db_index | |
| assignment | FK(CandidateAssignment, CASCADE) | |
| candidate / job | FK 冗余 | 便于列表查询与交接清单 |
| version | PositiveSmallIntegerField | 同 assignment 内自增（max+1），从 1 起 |
| status | CharField(16) | DRAFT / SENT / ACCEPTED / REJECTED / WITHDRAWN，默认 DRAFT |
| salary_amount | DecimalField(14,2) null | 月薪/年薪由业务字段表达，本表只存数值与币种 |
| currency | CharField(16) 默认 CNY | |
| approval_status | CharField(16) 默认 PENDING | PENDING / APPROVED / REJECTED |
| approver_id | UUID null | 审批人（不建外键，项目惯例） |
| approved_at | DateTime null | |
| sent_at / accepted_at / rejected_at / withdrawn_at | DateTime null | 各动作时间戳 |
| note | TextField blank | 条件说明等 |
| attachment_name / attachment_path | CharField blank | Offer letter 附件 |
| user_id / create_time / update_time | | |

约束：UniqueConstraint(workspace_id, assignment, version)。

## 状态机

| 当前 | 允许流转 | 动作 | 审计 |
|---|---|---|---|
| DRAFT | SENT | send | OFFER_SEND |
| DRAFT | （编辑/审批） | update/approve | UPDATE / OFFER_APPROVE |
| SENT | ACCEPTED | accept | OFFER_ACCEPT + ASSIGNMENT_TRANSITION（auto HIRED） |
| SENT | REJECTED | reject | OFFER_REJECT |
| SENT | WITHDRAWN | withdraw | OFFER_WITHDRAW |
| ACCEPTED / REJECTED / WITHDRAWN | 无 | 新建下一版本（DRAFT，version+1） | CREATE |

- 非法流转 400（含当前状态与目标状态）。
- 新版本（Offer 重谈）仅当指派仍为 OFFER 状态时可创建（REJECTED/WITHDRAWN 后重谈），从 DRAFT 重新走流程；指派进入 HIRED 后不得再创建新 Offer（PRD §92/§103：HIRED 后不恢复原关联、不新建关联）。
- 仅 DRAFT 可编辑金额/币种/审批/备注/附件。

## 服务方法（OfferService，apps/hr/serializers/offer.py）

| 方法 | 权限 | 说明 |
|---|---|---|
| create_offer(assignment_id, data) | ADMIN | 指派须 status=OFFER 否则 400；version=max+1；审计 CREATE |
| update_offer(offer_id, data) | ADMIN | 仅 DRAFT；金额/币种/note；审计 UPDATE |
| approve_offer(offer_id, data) | ADMIN | approval_status/approver_id；approved_at；审计 OFFER_APPROVE |
| send_offer(offer_id) | ADMIN | DRAFT→SENT + sent_at；审计 OFFER_SEND |
| accept_offer(offer_id) | ADMIN | SENT→ACCEPTED + accepted_at；事务内指派→HIRED + ASSIGNMENT_TRANSITION 审计；事务后触发 B3 交接（见交接规格）；审计 OFFER_ACCEPT |
| reject_offer(offer_id, data) | ADMIN | SENT→REJECTED + rejected_at + note；审计 OFFER_REJECT |
| withdraw_offer(offer_id) | ADMIN | SENT→WITHDRAWN + withdrawn_at；审计 OFFER_WITHDRAW |
| list_offers(assignment_id) / get_offer(offer_id) | 任意 HR | 按 -version |
| upload/remove_attachment | ADMIN | 存 data/offer/{workspace}/；审计 UPDATE |
| download_attachment | OPERATOR/ADMIN | VIEWER 403 |

- 跨工作区一律 404；金额/币种/审批枚举非法 400。

## API

统一前缀：/admin/api/workspace/{workspace_id}/hr。

| 方法 | 路径 | 权限 |
|---|---|---|
| GET | /assignments/{assignment_id}/offers | 任意 HR |
| POST | /assignments/{assignment_id}/offers | ADMIN |
| GET | /offers/{offer_id} | 任意 HR |
| PUT | /offers/{offer_id} | ADMIN |
| PUT | /offers/{offer_id}/approve | ADMIN |
| PUT | /offers/{offer_id}/send | ADMIN |
| PUT | /offers/{offer_id}/accept | ADMIN |
| PUT | /offers/{offer_id}/reject | ADMIN |
| PUT | /offers/{offer_id}/withdraw | ADMIN |
| POST | /offers/{offer_id}/attachment | ADMIN（multipart） |
| DELETE | /offers/{offer_id}/attachment | ADMIN |
| GET | /offers/{offer_id}/attachment | OPERATOR/ADMIN |

## 前端

- jobs/index.vue：OFFER 状态指派行加「Offer」按钮 → Offer 抽屉：
  - 版本列表（版本号、金额/币种、审批状态、状态、时间戳、附件）。
  - 「新建版本」表单（金额、币种、备注）；编辑/审批/发送/接受/拒绝/撤回按钮按状态禁用。
  - 附件上传/下载（ADMIN）/删除。
- 操作按钮：接受需确认弹窗（提示将自动进入 HIRED 并触发入职交接）。

## 测试

- 服务层：创建（版本自增、非 OFFER 指派 400、金额非法 400）；仅 DRAFT 可编辑；审批枚举 400；发送；接受（指派自动 HIRED + 双审计 + 二次接受 400）；拒绝；撤回；非法流转 400；跨工作区 404；OPERATOR 403；附件上传/下载/VIEWER 下载 403。
- 路由层：全链路（创建→审批→发送→接受后 GET 指派状态为 HIRED）；非 ADMIN 403 + ACCESS_DENIED 审计。
- 回归：既有 255 用例全部通过。

## 验收

HR 全量 PASS、makemigrations 无漂移、ruff 干净、vue-tsc 与双构建 PASS。
