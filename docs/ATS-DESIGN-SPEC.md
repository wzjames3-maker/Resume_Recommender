# ATS 精确设计规格（模糊点裁决与领域规范）

> 文档状态：设计规格，2026-08-18。本文件解决 `docs/PRD.md` 中 ATS 设计「表述模糊、枚举不闭合、状态联动未定义、与实现脱节」的问题：以当前代码事实（v2 分支，2026-08-18 基线）为准把每个模糊点裁决为**唯一确定的行为**。
>
> 标注约定：
> - **【F】事实**：代码已如此实现，本规格固化；修改须走规格变更评审。
> - **【R】裁决**：本规格新裁决、代码尚未实现的行为，汇总于 §11 待实现清单（附验收标准）。
>
> 权威顺序：**代码实现 > 本规格 > PRD.md（产品意图）**。与本规格冲突的 PRD 表述按 §10 清单回写修订。本规格只记录当前代码事实；目标态见 `docs/ATS-STATE-MACHINE-V2.md`，Agent/RAG 层设计见 `docs/PRD-AGENT-RAG.md`。

## 1. 模糊点裁决总表

| # | 模糊点 | PRD 原表述 | 代码事实 / 空白 | 裁决 | 类型 |
|---|---|---|---|---|---|
| D1 | 枚举不闭合 | 渠道/终止原因/关闭原因只说「受控枚举」 | 枚举值只存在于代码 | §2 全量闭合 | F |
| D2 | 终止原因与终态无适配 | 「受控拒绝原因」 | 任何终态可配任何原因（REJECTED 可配 JOB_CLOSED，统计口径混乱） | §4.3 适配矩阵，服务端校验 | R |
| D3 | Assignment/Offer/Interview 三状态体系联动未定义 | 「面试反馈不自动改变状态」「OFFER 记录结论」 | 联动规则散落代码，无文档 | §5 联动总表 | F+R |
| D4 | 审批与发送的关系 | 「审批」（Offer 工件） | `send_offer` 不检查 `approval_status`，未审批可直接发送 | 发送前置 = 审批通过 | R |
| D5 | 多 Offer 版本并存规则 | 「版本」 | 允许多版本；多个 SENT 可并存 | 同一关联同一时刻至多一个 SENT | R |
| D6 | 面试创建守卫 | 「进入面试前可先创建或后补第一轮面试」 | `create_interview` 不检查关联状态（PENDING_SCREEN 也能建面试） | 仅 SCREEN_PASSED / INTERVIEWING 可建 | R |
| D7 | 面试轮次编号规则 | 「轮次」 | `round_no` 可传任意整数，无唯一性/连续性约束 | 服务端强制连续递增，不信任客户端传值 | R |
| D8 | 推进 OFFER 的前置 | 「面试结果辅助推进」 | INTERVIEWING→OFFER 无面试完成度守卫 | 至少存在一轮面试且无 PENDING 轮 | R |
| D9 | 「待我处理」队列无契约 | 「负责人从待我处理队列按职位、状态、城市、渠道、负责人筛选」 | 无独立 assignments 列表端点；候选人列表的 owner 过滤是替代品（按候选人去重，非队列） | §6 新端点契约 | R |
| D10 | DRAFT 职位编辑权 | 「仅负责人和管理员可编辑」 | 代码仅 ADMIN（负责人被拒） | DRAFT 允许 owner（任意 HR 资格）或 ADMIN；非 DRAFT 仅 ADMIN | R |
| D11 | 候选人主档编辑权 | 未明说（操作员「维护筛选与面试信息」易误读） | 代码仅 ADMIN | 固化：主档编辑仅 ADMIN；操作员可维护的是关联备注/负责人与面试信息 | F |
| D12 | Offer「有权限人员」 | 「由具备权限的人员维护」 | 全生命周期（建/审/发/受/拒/撤/附件）仅 ADMIN | 固化进 §7 权限矩阵 | F |
| D13 | Offer 附件变更守卫 | 无 | 任意状态可上传/移除附件 | 仅 DRAFT 可变更附件（查看不限） | R |
| D14 | 职位初始状态 | DRAFT 是四态之一 | `create_job` 默认 OPEN，不接受 status 参数 | 创建时可显式 DRAFT/OPEN；ON_HOLD/CLOSED 不可作为初始态 | R |
| D15 | 关闭职位的「逐项处理」 | 「逐项处理或批量收尾」 | 仅批量：close 时活跃关联统一置 CLOSED/JOB_CLOSED | 固化：关闭动作=批量收尾剩余活跃关联；「逐项」= 关闭前人工先终止，系统在关闭预览中提示在途数量 | F+R |
| D16 | PRD 交付状态过时 | §4.5「OFFER 当前仅是流程状态」；§9.1「重排未接入」「语义检索未交付」 | B/C 阶段均已交付 | 按 §10 清单回写 PRD.md | 文档修正 |

## 2. 枚举闭合表（唯一权威取值）

来源 `apps/hr/models/recruitment.py`；前端枚举、导入模板、统计口径必须与此一致。

| 枚举 | 取值 | 用在 | 说明 |
|---|---|---|---|
| `ResumeChannel` 渠道 | `REFERRAL` 内推 / `JOB_SITE` 招聘网站 / `HEADHUNTER` 猎头 / `CAMPUS` 校园 / `OTHER` 其他 | 候选人来源 `source_type`、关联 `channel`、简历 `source_channel` | 人才库首次来源 ≠ 每次关联渠道 |
| `RelationType` 关系类型 | `APPLY` 投递 / `SEEK` 主动寻访 / `REFERRAL` 内推 / `HEADHUNTER` 猎头推荐 | 关联 `relation_type` | |
| `JobStatus` | `DRAFT` / `OPEN` / `ON_HOLD` / `CLOSED` | 职位 `status` | |
| `JobCloseReason` | `FILLED` 招满 / `CANCELLED` 取消 / `DUPLICATE` 重复需求 / `OTHER` 其他 | 职位 `close_reason` | 仅 CLOSED 可非空 |
| `AssignmentStatus` | `PENDING_SCREEN` / `SCREEN_PASSED` / `INTERVIEWING` / `OFFER` / `HIRED` / `REJECTED` / `WITHDRAWN` / `CLOSED` | 关联 `status` | 前四为活跃态，后四为终态（HIRED 亦终态） |
| `TerminationReason` | `NOT_FIT` 不适合 / `SALARY` 薪酬 / `UNREACHABLE` 无法联系 / `CANDIDATE_WITHDRAW` 候选人退出 / `JOB_CLOSED` 职位关闭 / `MERGED` 合并 / `OTHER` 其他 | 关联 `termination_reason` | 与终态的适配见 §4.3（R） |
| `ConsentStatus` 告知状态 | `UNKNOWN` / `NOTIFIED` 已告知 / `CONSENTED` 已同意 / `NOT_REQUIRED` 无需 | 候选人 `consent_status` | |
| `ContactPreference` | `EMAIL` / `PHONE` / `NO_CONTACT` 勿联 / `UNSPECIFIED` | 候选人 `contact_preference` | |
| `InterviewStatus` | `PENDING` / `PASSED` / `FAILED` / `NO_SHOW` / `CANCELLED` | 面试 `status` | 见 §4.5 设置权限 |
| `OfferStatus` | `DRAFT` / `SENT` / `ACCEPTED` / `REJECTED` / `WITHDRAWN` | Offer `status` | |
| `OfferApprovalStatus` | `PENDING` / `APPROVED` / `REJECTED` | Offer `approval_status` | |
| `HandoffStatus` | `PENDING` / `SUCCESS` / `FAILED` | 交接 `status` | 仅 FAILED 可重试 |
| `HandoffTargetType` | `CHECKLIST` 人工清单 / `WEBHOOK` 投递 | 交接目标、HrConfig | |
| `CandidateStatus` | `ACTIVE` / `ARCHIVED` / `DELETED` | 候选人 `status` | DELETED 仅 ADMIN 可见/查询 |
| `ResumeStatus` | `PENDING` / `SUCCESS` / `FAILED` | 简历 `status` | |
| `ResumeDatabaseStatus` | `ACTIVE` / `ARCHIVED` | 简历库 `status` | 总库只能 ACTIVE；业务库可归档 |
| `HrRole` | `VIEWER` / `OPERATOR` / `ADMIN` | HrAccess `role` | |
| `HrAuditAction` | 26 值（`apps/hr/models/recruitment.py:380`） | 审计 | Agent 增补动作见 PRD-AGENT-RAG §8 |

## 3. 领域对象字段规格

类型为 Django 字段类型；「必填」指服务端校验口径。所有表均含 `workspace_id`（租户隔离，服务端从认证主体派生，不信任 URL）；`user_id` 为创建人；`create_time/update_time` 为审计时间戳。

### 3.1 Candidate（`hr_candidate`）

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| name | Char(128) | 是 | 索引 |
| email | Email | 否 | 查重按 `iexact`；VIEWER 脱敏 `ab***@domain` |
| phone | Char(20) | 否（见 §11-E1） | 查重按精确等值；VIEWER 脱敏 `138****1234` |
| current_city / target_city | Char(64) | 否 | 筛选时两字段 OR 匹配 |
| highest_degree | Char(32) | 否 | 自由文本（不做枚举，历史数据不可控） |
| years_experience | PositiveSmallInt | 否 | |
| skills | JSON 数组 | 否 | 非空字符串数组；归一副表见 3.2 |
| source | Char(64) | 否 | 自由文本补充 |
| source_type | `ResumeChannel` | 默认 OTHER | 人才库首次来源 |
| source_detail | Char(128) | 否 | 来源=OTHER 时的详情 |
| collected_at | DateTime | 否 | 收集日期 |
| consent_status / consent_version / contact_preference | 见 §2 | 默认 UNKNOWN/空/UNSPECIFIED | 合规元数据 |
| note | Text | 否 | 4096 上限；禁止记录敏感属性（PRD §2.2） |
| status | `CandidateStatus` | 默认 ACTIVE | |

### 3.2 CandidateSkill（`hr_candidate_skill`，技能归一副表）

`candidate` FK(CASCADE)、`skill_norm`（归一形，索引）、`skill_raw`（原文）；唯一约束 (candidate, skill_norm)。由解析/导入写入，支撑 Skill-AND 的 SQL 精确匹配；`skills` JSON 为展示真源。

### 3.3 Job（`hr_job`）

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| name | Char(128) | 是 | |
| department / city / level | Char(128/64/64) | 否 | |
| headcount | PositiveSmallInt | 默认 1 | DB Check ≥1；服务端 1–999 |
| description | Text | 否 | 4096 上限 |
| skill_requirements | JSON 数组 | 否 | 非空字符串数组 |
| status | `JobStatus` | 默认 OPEN（R：可显式 DRAFT） | |
| close_reason | `JobCloseReason` | 终态必填 | 仅 CLOSED 可非空 |
| owner_id | UUID | 否 | 负责人；缺省视为创建人 |

### 3.4 CandidateAssignment（`hr_candidate_assignment`）

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| candidate / job | FK(PROTECT) | 是 | 删除保护，防级联丢历史 |
| status | `AssignmentStatus` | 默认 PENDING_SCREEN | 部分唯一索引：同候选人同职位**至多一条活跃关联**（DB 强制） |
| relation_type | `RelationType` | 默认 APPLY | |
| channel | `ResumeChannel` | 默认 OTHER | R：增 `channel_detail`（=OTHER 时必填） |
| applied_at | DateTime | 默认 now | 可回填 |
| termination_reason | `TerminationReason` | 终态必填 | 适配矩阵见 §4.3（R） |
| is_reapply | Bool | 默认 False | 创建时自动判定：存在历史终态关联即 True |
| note | Text | 否 | 4096；筛选备注（与候选人通用备注、面试反馈三者不得混用） |
| owner_id | UUID | 否 | 关联负责人，缺省创建人 |

### 3.5 Interview（`hr_interview`）

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| assignment | FK(CASCADE) | 是 | |
| round_no | PositiveSmallInt | 是 | R：服务端强制 = max+1 |
| interviewer | Char(64) | 否 | 外部面试官姓名；与 user 二选一 |
| interviewer_user_id | UUID | 否 | 用户化面试官；两者均空时保存报错 |
| scheduled_at / feedback_deadline | DateTime | 否 | 反馈逾期 = PENDING 且 deadline < now |
| status | `InterviewStatus` | 默认 PENDING | |
| feedback | Text | 否 | 4096；属关联业务资料，可重复提交修改 |

### 3.6 Offer（`hr_offer`）

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| assignment / candidate / job | FK(CASCADE) | 是 | 冗余 candidate/job 便于独立分页 |
| version | PositiveSmallInt | 是 | 唯一约束 (workspace, assignment, version)；服务端 = max+1 |
| status | `OfferStatus` | 默认 DRAFT | |
| salary_amount | Decimal(14,2) | 否 | |
| currency | Char(16) | 默认 CNY | |
| approval_status / approver_id / approved_at | | 默认 PENDING | R：发送前置 APPROVED |
| sent_at / accepted_at / rejected_at / withdrawn_at | DateTime | 否 | 各终态时间戳 |
| attachment_name / attachment_path | Char | 否 | 对象存储；R：仅 DRAFT 可变更；下载 OPERATOR+（服务层强制） |

### 3.7 OnboardingHandoff（`hr_onboarding_handoff`）

`assignment` FK(CASCADE)、`offer` FK(CASCADE)、`status`（PENDING/SUCCESS/FAILED）、`payload`（投递内容）、`attempts`、`last_error`、`handoff_time`。唯一约束 (workspace, assignment)——**幂等锚点**：每关联至多一次入职交接，不重复创建员工记录。目标类型与 webhook 由 HrConfig 配置；仅 FAILED 可重试。

### 3.8 ResumeFile（`hr_resume_file`）/ HrConfig / ResumeFlowLog / HrAccess / HrAuditLog

- ResumeFile：`file_name/extension(docx|txt)/file_path/file_size/sha256/status(PENDING|SUCCESS|FAILED)/error_message/candidate FK(SET_NULL)/source_channel/document_id`（语义索引文档 id，删除/TTL 联动清理）。唯一约束 (workspace, sha256)。
- HrConfig：每工作区一行——`llm_model_id`、`rerank_model_id`、`handoff_target_type`、`handoff_webhook_url`（Agent 扩展字段见 PRD-AGENT-RAG §8）。
- ResumeFlowLog：简历六节点流转日志（UPLOAD/EXTRACT/SANITIZE/SPLIT/DOCUMENT/LIFECYCLE），EXTRACT/SANITIZE 含未脱敏全文，**仅 OPERATOR+ 可读**。
- HrAccess：(workspace, user) 唯一，role 三值。
- HrAuditLog：只增不改；`action(26 值)/object_type/object_id/result(SUCCESS|FAILED|DENIED)/detail`。

### 3.9 ResumeDatabase 与 ResumeDatabaseMembership

- ResumeDatabase：workspace_id、name、description、status、is_default、is_system、user_id；每个 workspace 自动维护一个 is_system=true 的“总库”，总库不能归档。
- ResumeDatabaseMembership：resume_file、resume_database、create_time；唯一约束是 (resume_file, resume_database)，是实际多库归属真源。
- ResumeFile.resume_database 仍保留为主归属和旧接口兼容字段；物理文件、解析结果和语义索引按 workspace + sha256 去重，重复上传到其他库只新增成员关系。
- 业务库归档保留历史成员关系，但从上传、候选人库筛选和 RAG 有效选择范围中排除。

## 4. 状态机规格

### 4.1 Candidate

| 迁移 | 角色 | 守卫 | 副作用 |
|---|---|---|---|
| ACTIVE→ARCHIVED | ADMIN | 无活跃关联（四活跃态任一存在即 400） | 审计 ARCHIVE |
| ARCHIVED→ACTIVE | ADMIN | — | 审计 RESTORE |
| 任意→DELETED | ADMIN | — | 异步清除：PII 清空、简历原件/文本/解析/语义索引/流转日志级联；保留去标识化统计与审计引用 |

DELETED 对非 ADMIN 按不存在处理（列表默认排除，详情 404）。

### 4.2 Job

| 迁移 | 角色 | 守卫 | 副作用 |
|---|---|---|---|
| 创建（默认 OPEN；R：可显式 DRAFT） | ADMIN | — | 审计 CREATE |
| 任意编辑 | ADMIN（R：DRAFT 另允许 owner） | CLOSED 不可直接改出（必须 reopen）；close_reason 仅 CLOSED 可设 | 审计 UPDATE |
| OPEN↔ON_HOLD | ADMIN | 经编辑接口 status 字段 | 无 |
| →CLOSED | ADMIN | close 端点 + close_reason 必填 | **批量收尾**：全部活跃关联置 CLOSED + JOB_CLOSED（事务内）；返回收尾数量；审计 JOB_CLOSE |
| ON_HOLD/CLOSED→OPEN | ADMIN | reopen 端点 | 清空 close_reason；审计 JOB_REOPEN |

DRAFT→OPEN 无字段完整性前置校验【F，维持：DRAFT 是轻量草稿，不设门槛】。

### 4.3 CandidateAssignment（核心状态机）

迁移矩阵（`_ALLOWED_TRANSITIONS`，服务端强制，越界 400）：

| 源状态 | 允许目标 | 附加守卫（逐边） |
|---|---|---|
| PENDING_SCREEN | SCREEN_PASSED | 候选人须 ACTIVE（目标为活跃态时）；**不要求 job=OPEN**（初筛可在职位暂停时完成） |
| PENDING_SCREEN / SCREEN_PASSED | REJECTED / WITHDRAWN / CLOSED | termination_reason 必填 |
| SCREEN_PASSED | INTERVIEWING | 候选人 ACTIVE **且** job=OPEN（`JOB_OPEN_REQUIRED_TARGETS`：INTERVIEWING/OFFER/HIRED 三目标要求职位开放） |
| INTERVIEWING | OFFER | job=OPEN；R：至少一轮面试存在且无 PENDING 轮 |
| INTERVIEWING / OFFER | REJECTED / WITHDRAWN / CLOSED | termination_reason 必填 |
| OFFER | HIRED | job=OPEN；正常路径=Offer 接受自动迁移（§5），直接手工迁 HIRED 允许但不写 Offer 结论（不推荐，审计可查） |
| REJECTED | PENDING_SCREEN | **仅 ADMIN**；恢复原因必填（写入 note `[restore]` 前缀）；无其他活跃关联；清空 termination_reason；审计 detail=RESTORE |
| WITHDRAWN / CLOSED / HIRED | 无 | 不恢复原关联；重新参与=新建关联（is_reapply 自动置 True） |

**创建守卫**（事务 + `select_for_update`）：job=OPEN；候选人无 HIRED 历史；唯一活跃关联（DB 部分唯一索引兜底并发）。

**终止原因×终态适配矩阵【R】**（服务端校验，杜绝统计口径污染）：

| 终态 | 允许的 termination_reason |
|---|---|
| REJECTED | NOT_FIT / SALARY / OTHER |
| WITHDRAWN | CANDIDATE_WITHDRAW / UNREACHABLE / OTHER |
| CLOSED | JOB_CLOSED / MERGED / OTHER |

### 4.4 Offer 工件

| 迁移 | 角色 | 守卫 |
|---|---|---|
| 创建（任意版本号 = max+1） | ADMIN | **assignment.status = OFFER**（唯一入口，HIRED 后自然不可建） |
| 编辑（金额/币种/备注） | ADMIN | 仅 DRAFT |
| 审批（通过/驳回） | ADMIN | 仅 DRAFT；APPROVED 时写 approved_at |
| DRAFT→SENT | ADMIN | R：approval_status = APPROVED；R：同关联无其他 SENT |
| SENT→ACCEPTED | ADMIN | 事务内：写 accepted_at + assignment→HIRED + 审计 + 创建并投递 handoff |
| SENT→REJECTED / WITHDRAWN | ADMIN | 写对应时间戳；**assignment 不变**（停留 OFFER，处置见 §5） |

### 4.5 Interview

| 迁移 | 操作者 | 守卫 |
|---|---|---|
| 创建 | OPERATOR+ | R：assignment ∈ {SCREEN_PASSED, INTERVIEWING}；round_no 服务端 = max+1 |
| PENDING→PASSED/FAILED/NO_SHOW | **面试官本人**（登录即可，无需 HR 资格；非本人一律 404） | 反馈提交接口；可重复提交修改；写 feedback_submitted_at + 审计 |
| →CANCELLED（及其他字段编辑） | OPERATOR+ | 编辑接口 |
| （不变式） | — | 面试状态**永不**自动改变关联状态；反馈逾期仅标记 is_overdue |

## 5. 三状态体系联动总表（D3 裁决）

| 场景 | 系统行为 |
|---|---|
| 关联进入 OFFER（人工迁移） | 可创建 Offer v1（ADMIN）；建多版本允许（谈判历史留痕） |
| Offer 处于 DRAFT | 可编辑/审批/变更附件；未审批不可发送（R） |
| Offer SENT | 等待结论；同关联不可再发送其他版本（R）；attachment/编辑锁定 |
| Offer ACCEPTED | 同一事务：assignment→HIRED（审计 detail=`auto to HIRED via offer accept`）→ 创建 handoff（幂等）→ 立即投递（CHECKLIST 记录 / WEBHOOK 外呼） |
| Offer REJECTED / WITHDRAWN | Offer 终态；**关联停留 OFFER**，两条出路由人选择：① 创建下一版本继续谈 ② 终止关联（REJECTED+SALARY/NOT_FIT 或 WITHDRAWN+CANDIDATE_WITHDRAW） |
| 关联长期停留 OFFER 且无在途 Offer 版本 | 无自动处理（人工责任）；R：队列中显示「Offer 停滞」提示（超过 7 天无 DRAFT/SENT 版本） |
| 面试全部轮次 FAILED | 关联不自动变化；由负责人决策终止（REJECTED+NOT_FIT）或加轮 |
| Offer 接受后再次创建 Offer | 不可能：create_offer 守卫 assignment=OFFER，HIRED 已不满足 |

## 6. 「待我处理」队列契约【R，D9】

新增端点：`GET /workspace/{ws}/hr/assignments/page/{page}/{size}`

| 参数 | 默认 | 说明 |
|---|---|---|
| owner_id | 当前用户 | 「待我处理」语义；ADMIN 可传其他用户或 `all` |
| status | 活跃四态 | `terminal=1` 时含终态（含 is_reapply 历史查询） |
| job_id / channel / relation_type / city | 无 | city 匹配候选人 current/target_city |
| q | 无 | 候选人姓名/手机/邮箱前缀定位（不依赖 AI） |

返回行 = 关联 + candidate_name + job_name + 最新面试轮次（round_no/status/overdue）+ Agent 建议徽标（D1 后，见 PRD-AGENT-RAG §11）。排序 `update_time DESC`。现状替代品（候选人列表 owner 过滤）保留但语义不同（按候选人聚合），不得冒充队列。

## 7. 权限矩阵（对象 × 操作 × 角色）【F】

| 对象.操作 | VIEWER | OPERATOR | ADMIN |
|---|---|---|---|
| 候选人：列表/详情/查重/AI 语义搜索 | ✓（phone/email 脱敏；DELETED 不可见） | ✓（明文） | ✓ |
| 候选人：创建 | ✗ | ✓ | ✓ |
| 候选人：主档编辑/归档/恢复/删除/合并/导出（白名单 14 字段）/CSV 导入 | ✗ | ✗ | ✓ |
| 简历：上传/下载/原文/批量状态/流转日志 | ✗ | ✓ | ✓ |
| 简历：详情（含候选人口径） | ✗ | ✗ | ✓ |
| 简历库：查看、库内候选人、库内检索 | ✓ | ✓ | ✓ |
| 简历库：创建、归档业务库 | ✗ | ✗ | ✓ |
| 职位：创建/编辑/关闭/重开 | ✗ | ✗ | ✓（R：DRAFT 编辑另允许 owner） |
| 职位/关联：列表/详情/匹配 | ✓ | ✓ | ✓ |
| 关联：创建/状态迁移/备注/负责人/面试管理 | ✗ | ✓（恢复与设回 PENDING_SCREEN 需 ADMIN） | ✓ |
| 面试：我的面试/提交反馈 | 登录即可（面试官无需 HR 资格；仅本人记录，无 PII，仅姓名+职位名） | 同左 | 同左 |
| Offer：查看/独立分页 | ✓ | ✓ | ✓ |
| Offer：创建/审批/编辑/发送/接受/拒绝/撤回/附件管理 | ✗ | ✗ | ✓ |
| Offer：附件下载 | ✗ | ✓（服务层强制） | ✓ |
| Handoff：查看/重试 | 查看 ✓ / 重试 ✗ | 查看 ✓ / ✗ | ✓ |
| 越权访问 | 统一 404/403 + ACCESS_DENIED 审计 | | |

## 8. 业务规则细目

- **查重**：phone 精确等值 OR email `iexact`；列表行附着 `duplicate_ids`；合并仅 ADMIN（保留主档，副档关联迁移）。
- **简历 TTL**：上传 30 自然日未关联候选人 → 后台删除原件/文本/解析结果/语义索引，级联清理流转日志节点，记 LIFECYCLE 日志。
- **简历库**：总库自动加入每份简历，业务库通过 ResumeDatabaseMembership 多对多归属；上传总库强制保留，重复 SHA-256 文件跨库复用；归档库不接收新上传和检索。
- **导出白名单**（`CANDIDATE_EXPORT_FIELDS`，14 字段）：name/status/city×2/degree/years/skills/source×3/collected_at/consent_status/contact_preference/create_time——**不含联系方式与备注**。
- **脱敏格式**：phone `前3****后4`；email `前2***@域名`。
- **CSV 导入**：≤200 行 ≤2MB；逐行校验、失败原因报告、疑似重复标注。
- **三类备注不得混用**：候选人 `note`（人才库通用）、关联 `note`（筛选过程）、面试 `feedback`（轮次评估）——各自归属各自展示，互不回落。

## 9. API 面清单（apps/hr/urls.py）

| 分组 | 端点（前缀 `/admin/api/workspace/{ws}/hr`） |
|---|---|
| 候选人（8） | `candidates` CRUD/分页/查重/归档/恢复/删除/合并/导出 |
| 简历（7） | 上传（`candidates/resumes`）/列表/详情/下载/原文/批量状态/流转日志 |
| 简历库（3） | resume-databases GET/POST、resume-databases/{id}/archive；总库、多业务库统计和归档 |
| 语义检索（1） | `resumes/search`（POST，模式 A/B，见检索设计文档） |
| 职位（7） | `jobs` CRUD/分页/关闭/重开/关联创建/匹配分页 |
| 关联（1） | `assignments/{id}`（详情 + 状态迁移）；R：+ 队列分页（§6） |
| 面试（3） | 按关联创建/列表、详情编辑、面试官 mine/feedback |
| Offer（9） | 按关联创建/列表、独立分页、详情/审批/发送/接受/拒绝/撤回/附件三件套 |
| Handoff（2） | 列表/详情/重试 |
| 导入（2） | 模板/导入 |
| 其他（4） | access 管理、config、audit、agent（D1 增） |

## 10. PRD.md 回写修正清单（随本规格执行）

1. §4.5「`OFFER` 当前仅是流程状态……」→ 已过时，改为引用本规格 §4.4/§5（B 阶段已交付完整 Offer 工件）。
2. §9.1 已交付表：「知识库/Embedding 语义检索未交付」与「重排未接入检索流水线」→ C 阶段已交付（recall@5=0.92），补交付行。
3. §4.3 渠道与终止原因 → 引用 §2 闭合枚举与 §4.3 适配矩阵。
4. §5.2「待我处理」→ 对齐 §6 契约（标注待实现）。
5. §6「语义索引如后续启用」→ 已启用表述。
6. 文档头增加本规格与 `PRD-AGENT-RAG.md` 的引用关系。

## 11. 待实现清单（含验收标准）

**本规格新裁决引入：**

| # | 规则 | 验收标准 |
|---|---|---|
| R-D2 | 终止原因×终态适配校验 | REJECTED 提交 JOB_CLOSED → 400；适配矩阵内通过 |
| R-D4 | 发送前置审批 | approval_status≠APPROVED 时 send → 400 |
| R-D5 | 至多一个 SENT | 同关联存在 SENT 时另一版本 send → 400 |
| R-D6 | 面试创建守卫 | PENDING_SCREEN 关联建面试 → 400；SCREEN_PASSED/INTERVIEWING 通过 |
| R-D7 | round_no 连续 | 传入 ≤max 值 → 400 或忽略按 max+1；不信任客户端 |
| R-D8 | OFFER 推进守卫 | 无面试记录或存在 PENDING 轮时 INTERVIEWING→OFFER → 400 |
| R-D9 | 队列端点 | §6 契约全参数过滤 + 排序 + 权限（OPERATOR 默认本人）自动化测试 |
| R-D10 | DRAFT owner 编辑 | owner(OPERATOR) 编辑 DRAFT 通过；OPEN 仍 403；非 owner OPERATOR → 403 |
| R-D13 | 附件变更仅 DRAFT | SENT 后上传/移除附件 → 400 |
| R-D14 | 创建显式 DRAFT | `status=DRAFT` 生效；`status=CLOSED` → 400 |
| R-D15 | 关闭预览 | close 前可查询在途关联数量（只读接口或 close 响应 dry-run） |
| R-D16 | Offer 停滞提示 | 队列行含 `offer_stalled` 标记（>7 天无 DRAFT/SENT） |
| R-渠道详情 | 关联 `channel_detail` | channel=OTHER 时必填，迁移 + 前端 |

**既有缺口（PRD 已标注，纳入统一跟踪）：**

| # | 缺口 | 出处 |
|---|---|---|
| E1 | 建档校验「姓名 + 至少一种联系方式」 | PRD §4.1/§8（未实现） |
| E2 | HrAuditLog `trace` 字段 | PRD §7（未实现；Agent 链路依赖，见 PRD-AGENT-RAG §14） |
| E3 | 前端 HR 菜单/路由按 HrRole 门控、VIEWER 简历/Offer 附件入口收敛 | 当前实现（历史前端审查结论，待迁移到 v2 验收） |
| E4 | AI 检索结果补城市依据 | 当前实现（历史前端审查结论，待迁移到 v2 验收） |
