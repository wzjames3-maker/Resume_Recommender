# 面试协作设计（B1：面试官最小可见、反馈截止与可追溯）

## 背景

PRD §4.5 与 §9.2（B 阶段）要求完整面试协作：面试官最小可见（§42「面试官在面试协作阶段仅能看到完成反馈必需的候选人与职位信息」）、反馈可追溯、反馈截止。当前 Interview.interviewer 仅为文本字段，无面试官身份、无截止时间、反馈不可追溯（见 HANDOFF.md §5.2）。

## 范围

### 范围内

- Interview 新增 interviewer_user_id（面试官用户，UUID 不建外键，项目惯例）、feedback_deadline（反馈截止时间）、feedback_submitted_at（反馈提交时间，可追溯）。
- 面试官身份校验与隔离：仅被指派的面试官本人可查看「我的面试」并提交反馈；非本人一律 404（不泄露存在性）。
- 面试官最小可见：我的面试列表只返回候选人姓名、职位名、轮次、时间、状态、截止时间——不含联系方式、简历、技能等其余信息。
- 反馈可追溯：提交反馈写时间戳并审计（新动作 INTERVIEW_FEEDBACK）。
- 反馈截止：安排面试可设置截止时间；列表展示截止与逾期状态（is_overdue 计算字段）；不实现自动提醒（四期明确排除，B 阶段亦未要求）。
- 决策记录：指派流转决策由既有 ASSIGNMENT_TRANSITION 审计 + 面试反馈时间戳构成可追溯链，不新增决策表。
- 前端：职位页面试抽屉增强（面试官成员选择、截止时间、逾期展示）；新增「我的面试」页面（面试官提交反馈）。

### 不在范围内

- 自动提醒与超时流转；Offer 工件、入职交接、批量导入（B2/B3/B4）。
- 面试官可见简历/联系方式；面试官之间互不可见。

## 数据模型

### Interview 新增字段

| 字段 | 类型 | 规则 |
|---|---|---|
| interviewer_user_id | UUIDField(null=True, blank=True) | 面试官用户 ID；安排时可空（仅文本面试官，向后兼容） |
| feedback_deadline | DateTimeField(null=True, blank=True) | 反馈截止时间 |
| feedback_submitted_at | DateTimeField(null=True, blank=True) | 面试官最后一次提交反馈时间 |

- interviewer 文本字段保留：安排/更新面试官用户时自动填充其 nick_name 作为显示名；纯文本模式继续兼容旧数据与「临时外部面试官」场景。
- interviewer_user_id 若指定必须为当前工作区成员（复用 UserManageSerializer().get_user_members），否则 400。

### HrAuditAction 新增

- INTERVIEW_FEEDBACK = "INTERVIEW_FEEDBACK", "Interview feedback"

## 服务方法（RecruitmentService）

| 方法 | 变更 |
|---|---|
| create_interview | 接受可选 interviewer_user_id、feedback_deadline；interviewer_user_id 非成员 400；自动填 interviewer 显示名 |
| update_interview | 接受可选 interviewer_user_id、feedback_deadline；变更面试官时同步显示名 |
| list_interviews | 响应增加 interviewer_user_id、feedback_deadline、feedback_submitted_at |
| list_my_interviews | 新：当前工作区内 interviewer_user_id == 当前用户 的面试列表；最小字段 + is_overdue；不做 hr_role 校验（面试官可无 HrAccess） |
| submit_interview_feedback | 新：interview_id 在工作区且 interviewer_user_id == 当前用户，否则 404；status 限 PASSED/FAILED/NO_SHOW，非法 400；写 feedback/status/feedback_submitted_at；审计 INTERVIEW_FEEDBACK；允许重复提交（刷新时间戳并追加审计） |

is_overdue：status == PENDING 且 feedback_deadline 非空且 feedback_deadline < now。

## API

统一前缀：/admin/api/workspace/{workspace_id}/hr。新接口仅 TokenAuth（面试官可无 HrAccess），隔离在服务层。

| 方法 | 路径 | 用途 | 权限 |
|---|---|---|---|
| POST | /assignments/{assignment_id}/interviews | 安排面试（扩展字段） | HR OPERATOR/ADMIN |
| PUT | /interviews/{interview_id} | 更新面试（扩展字段） | HR OPERATOR/ADMIN |
| GET | /assignments/{assignment_id}/interviews | 面试列表（扩展字段） | 任意 HR |
| GET | /interviews/mine | 我的面试（最小字段） | 登录用户（本人隔离） |
| PUT | /interviews/{interview_id}/feedback | 提交反馈 | 登录用户（本人隔离） |

路由顺序：/interviews/mine 静态段必须注册在 /interviews/<str:interview_id> 动态段之前（项目教训：静态段被动态段吞掉）。

我的面试响应字段：interview_id、assignment_id、round_no、scheduled_at、status、feedback、feedback_deadline、feedback_submitted_at、is_overdue、candidate_name、job_name。不含联系方式/简历/技能/其他面试官。

## 前端

- jobs/index.vue 面试抽屉：
  - 安排表单：「面试官」由文本输入改为成员下拉（复用 AuthorizationApi.getUserMember）+「反馈截止」datetime 选择器。
  - 记录列表：展示面试官（显示名）、截止时间、逾期 tag、已提交时间。
- 新页面 ui/src/views/hr/my-interviews/index.vue + 路由 /hr/my-interviews（menu 显示、不加 HrRoleConst 权限，工作区成员可见）：
  - 我的面试列表（候选/职位/轮次/时间/状态/截止/逾期）。
  - 反馈弹窗：结果下拉（通过/未通过/未到场）+ 反馈文本 → PUT feedback。
- api/hr/recruitment.ts：getMyInterviews、submitInterviewFeedback；createInterview/updateInterview 扩展字段透传。

## 测试

- 服务层：安排面试保存 interviewer_user_id/feedback_deadline 且自动填显示名；非成员 400；我的面试仅本人可见（跨用户隔离）且含 candidate_name/job_name/is_overdue；反馈提交成功（状态/反馈/时间戳/审计）；非本人 404；非法 status 400；重复提交更新；update_interview 变更面试官同步显示名。
- 路由层：GET /interviews/mine 200（验证静态段路由顺序）；非本人 PUT feedback 404；本人 200 + 审计；未登录 401。
- 回归：既有 240 用例全部通过。

## 验收

HR 全量测试 PASS、makemigrations --check --dry-run 无漂移、ruff check apps/hr/ 干净、vue-tsc 与 admin/chat 双构建 PASS、HANDOFF.md §5.2 面试协作项标记为已交付 v1。
