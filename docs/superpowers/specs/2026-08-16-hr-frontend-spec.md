# HR 招聘工作台前端规格（PRD 对齐版）

> 文档状态：前端实现基线，更新于 2026-08-16。本文以 docs/PRD.md（§3 角色边界、§4 业务对象与规则、§5 核心流程、§7 数据保护、§8 非功能要求、§9 交付状态）为唯一产品基线，描述 HR 模块前端的信息架构、页面规格、交互与状态机约束、接口契约与非功能要求。已交付实现以第 10 节为准；未列出的行为不得默认实现。

## 1. 定位与前端原则

### 1.1 定位（PRD §1）

人事招聘工作台是**嵌入精简版 MaxKB v2** 的多租户招聘模块。前端形态为 MaxKB 管理台（Vue 3 + Vite + Element Plus）中的一个菜单「人事部」，**不得**改变 MaxKB 管理台整体形态、品牌与导航；MaxKB 的认证、工作区、模型管理、知识库/问答等既有前端保持可用。

### 1.2 前端原则（PRD §2.2 映射）

| PRD 原则 | 前端含义 |
|---|---|
| 招聘需求优先 | 职位的状态/负责人/流程承载于「职位」页与「候选人-职位」指派，候选人档案页不混入流程字段。 |
| 关系承载流程 | 渠道/负责人/进度/结论属于**指派**（Assignment），前端在指派维度呈现与编辑，不写入候选人永久档案表单。 |
| 数据最小化 | 表单只采集完成招聘所需字段；不提供身份证/银行/健康/婚育等敏感自由文本输入位。 |
| 人工决策优先 | AI 搜索/技能抽取/匹配结果一律为**建议**：AI 搜索回填筛选条件后可再编辑；技能抽取回填表单可再编辑；匹配候选人需人工点击「加入职位」。任何 AI 能力不得直接改变候选人/指派状态。 |
| 先安全后扩展 | 联系方式默认脱敏展示（按角色）；导出/下载/合并/删除/授权为受限操作并触发审计；前端不做绕过服务端权限的展示分支。 |

## 2. 信息架构与导航

### 2.1 菜单形态

- 顶栏菜单保持 MaxKB 原有形态：Home | Agent | Knowledge | 人事部 | Model（hr 路由 order: 5，位置在 Knowledge 之后）。
- 「人事部」为一级菜单，点击进入 /hr/candidates（redirect）。
- HR 页面统一使用 SimpleLayout（顶栏 + 内容区），不引入侧边栏。

### 2.2 路由表

| 路由 | 页面 | 权限（PRD §3） |
|---|---|---|
| /hr/candidates | 候选人管理 | VIEWER+ |
| /hr/jobs | 职位管理与管道看板 | VIEWER+ |
| /hr/search | 简历语义检索 | VIEWER+ |
| /hr/my-interviews | 我的面试（仅本人数据） | 登录用户（面试官可无 HR 授权，服务端按本人隔离） |
| /hr/access | 人事成员授权 | ADMIN |
| /hr/audit-logs | 审计日志 | ADMIN |
| /hr/handoffs | 入职交接 | ADMIN |

- 菜单项按 HrRole 显隐（HrRoleConst），未授权访问由路由守卫导向无权限页，服务端同时记录越权拒绝审计。
- HR 角色来源：user.getHrRole()（后端 GET /hr/access/me 缓存于用户会话）。

## 3. 角色能力与界面显隐规则（PRD §3）

### 3.1 能力矩阵

| 能力 | 查看者 VIEWER | 操作员 OPERATOR | 管理员 ADMIN |
|---|---|---|---|
| 查看候选人/职位列表与详情 | 是（联系方式脱敏） | 是（明文） | 是（明文） |
| 新建/编辑候选人、上传简历、加入职位 | 否 | 是 | 是 |
| 面试安排/面试记录维护 | 否 | 是 | 是 |
| 「我的面试」反馈提交（仅本人） | 是（本人） | 是（本人） | 是（本人） |
| 归档/恢复/删除/合并候选人 | 否 | 否 | 是 |
| 职位新建/编辑/关闭/恢复、AI 技能抽取 | 否（只读） | 否 | 是 |
| 指派流转（拖拽/对话框） | 否（只读） | 是（终态需原因） | 是（含误拒恢复） |
| Offer 管理（审批/发送/接受/撤回/附件） | 附件不可下载 | 否 | 是 |
| 简历查看原文/下载/流转日志 | 否（OPERATOR+，EXTRACT/SANITIZE 含未脱敏全文） | 是 | 是 |
| 批量导入/导出候选人 | 否 | 否 | 是（导出白名单字段、不含联系方式） |
| 人事成员授权/审计日志/交接配置 | 否 | 否 | 是 |
| 简历语义检索 | 是（结果脱敏，SEARCH 审计） | 是 | 是 |

### 3.2 显隐实现规则

- 按钮/入口统一按 isHrOperator = getHrRole() ∈ {OPERATOR, ADMIN} 与 isHrAdmin = getHrRole() === 'ADMIN' 计算，**禁止**仅凭工作区角色判断 HR 操作权限。
- 受限操作（归档、删除、合并、导出、导入、授权、关闭职位、Offer 变更、简历删除/下载）执行前后触发服务端审计；前端文案需明确不可逆后果（如删除=匿名化并删除简历）。
- 脱敏展示：VIEWER 视角手机/邮箱显示后端返回的掩码；前端不得自行从其他字段拼装明文联系方式。

### 3.3 前后端权限一致性（现状与风险）

前端按钮一律按 HR 角色显隐（isHrOperator/isHrAdmin），但**部分后端写接口仅挂 `hr_access_required`**，VIEWER 直调 API 仍可成功，与 PRD §3「VIEWER 不得创建或变更流程」不符：

| 接口 | 后端门槛 | 前端暴露 | 状态 |
|---|---|---|---|
| POST /candidates（建档） | hr_access_required | OPERATOR+ | ⚠️ 后端应收紧 |
| POST /jobs/{id}/assignments（加入职位） | hr_access_required | OPERATOR+ | ⚠️ 后端应收紧 |
| POST /candidates/resumes（简历上传） | hr_access_required | OPERATOR+ | ⚠️ 后端应收紧 |
| POST /assignments/{id}/interviews（安排面试） | hr_access_required | OPERATOR+ | ⚠️ 后端应收紧 |
| PUT /interviews/{id}（面试记录更新） | hr_access_required | OPERATOR+ | ⚠️ 后端应收紧 |
| PUT /assignments/{id}（指派状态流转） | hr_access_required | OPERATOR+（拖拽/对话框） | ⚠️ 后端应收紧 |
| GET /offers/{id}/attachment/download（Offer 附件） | hr_access_required | 仅 ADMIN 可见入口 | ⚠️ 与 README「VIEWER 不可下载」不符，后端应收紧 |
| POST /ai/search-parse（AI 搜索） | hr_access_required | OPERATOR+ | 前端严于后端（VIEWER 直调可用，需确认产品口径） |
| GET /handoffs（交接列表） | hr_access_required | 页面 ADMIN-only | 前端严于后端 |
| GET /import/candidates/template | hr_access_required | ADMIN-only | 前端严于后端 |

统一口径：**前端显隐按 §3.1 矩阵；后端写操作应至少 `hr_operator_required`，Offer 附件下载按产品口径收紧**（待办，见 §10）。

## 4. 页面规格

### 4.1 候选人管理 /hr/candidates

**筛选区**（组合检索，条件变更即刷新）：
- 姓名、城市、技能（多技能 AND 由后端支持，前端逗号分隔输入）、工作年限区间（min/max）、最高学历（博士/硕士/本科/大专/中专/高中）、来源渠道（内推/招聘网站/猎头/校园/其他）、档案状态（在库/已归档）、「待我处理」（owner_id=当前用户，可切换）。
- AI 搜索（OPERATOR+）：自然语言 → POST /ai/search-parse → 回填筛选条件 → 提示「已按 AI 解析条件搜索，可继续修改」（人工决策优先）。
- AI 设置对话框（ADMIN）：工作区级 LLM/Rerank 模型选择（GET/PUT /ai/config，后端 ADMIN-only）；候选人/职位两页均有入口。

**列表**：姓名（加粗）、城市（现居→目标）、经验、技能、疑似重复标记（duplicate_ids 非空）、状态、操作。
- 操作列：主操作「详情」+「更多」下拉（按角色显隐）：编辑(ADMIN)、加入职位(OPERATOR+)、归档(ADMIN)、恢复(ADMIN)、简历、合并(ADMIN，需重复标记)、删除(ADMIN，分隔线置底)。
- 分页 20/页，AppTable。

**详情对话框**：基础信息 + 关联职位列表（职位名/指派状态/关系类型/渠道/负责人/备注），支持从详情恢复归档。

**新建/编辑表单**（对话框）：
- 必填：姓名（PRD §8 门槛为「姓名+至少一种联系方式」，当前服务端仅校验姓名——前端按 PRD 要求校验姓名必填、手机/邮箱二选一必填并提示，标注为待后端同步的门槛项）。
- 字段：姓名、邮箱、手机号、当前/目标城市、最高学历、工作年限、技能（逗号分隔）、来源类型/详情、收集日期、告知状态（未知/已告知/已同意/无需同意）、告知版本、联系偏好（邮箱/电话/不联系/未指定）、来源、备注（≤4096）。
- 保存前查重：POST /candidates/check-duplicate，命中则确认框「发现疑似重复候选人，是否继续保存？」（PRD §5.1）。


### 4.2 职位管理 /hr/jobs

**列表**：筛选（名称/状态/待我处理）；列：职位、部门、城市、HC（在途/编制）、状态 tag、负责人、操作（编辑/恢复/关闭，ADMIN）。

**表单**：名称（必填）、部门、城市、职级、招聘人数（1–999）、状态（草稿/开放/暂停；关闭态不可在表单内直接切换）、负责人、职位描述（≤4096）、技能要求（逗号分隔 + 「AI 抽取技能」，需描述非空，结果可编辑后保存）。
- 状态→关闭：走「关闭职位」对话框（原因：招满/取消/重复需求/其他 + 在途关联批量收尾提示 + 返回收尾数量）。

**展开区 — 管道看板**（候选人 tab）：
- 6 列：待筛选 → 筛选通过 → 面试中 → Offer 中 → 已入职 → 已结束（REJECTED/WITHDRAWN/CLOSED 收纳，只读）。
- 卡片：候选人名（重投标记）、渠道/关系类型 tag、负责人；操作：面试（OPERATOR+）、Offer（ADMIN 且 OFFER 态）、「更多」（编辑指派(ADMIN)/淘汰/候选人退出/关闭指派/恢复待筛选(ADMIN，仅 REJECTED)）。
- **拖拽规则（与 PRD §4.3 状态机一致）**：
  - 仅允许沿链**前进**：待筛选→筛选通过→面试中→Offer 中（PIPELINE_ORDER 索引校验，toIdx > fromIdx）。
  - 目标为已结束/已入职列不可拖入（拖入被拒或回滚并提示）。
  - 同列排序禁用（sort: false）；非法落点回滚并提示「只能按 … 顺序推进」。
  - 拖拽成功仅调 PUT /assignments/{id} {status}，成功后刷新看板数据（不整体刷新表格，保持展开态）。
  - 终态流转（淘汰/退出/关闭）必须弹「状态变更」对话框填写**受控终止原因**（不合适/薪资不符/无法联系/候选人退出/职位关闭/合并/其他）；误拒恢复（REJECTED→PENDING_SCREEN）仅 ADMIN，必填恢复原因（note 前缀 [restore]）。
- 「编辑指派」对话框：关系类型（投递/主动寻访/内推/猎头推荐）、渠道、负责人（工作区成员）、备注。

**展开区 — 匹配候选人 tab**：匹配分、命中技能、现居、操作「加入职位」（OPERATOR+，创建 PENDING_SCREEN 指派后刷新）。

### 4.3 面试（职位看板抽屉 + /hr/my-interviews）

**安排/记录对话框**（OPERATOR+）：轮次、面试官（工作区成员，可留空填临时面试官）、面试时间、反馈截止（可选）；列表列：轮次/面试官/时间/反馈截止（逾期红色、已提交标记）/结果（待面试/通过/未通过/未到场/取消）/反馈文本（变更即保存）。

**我的面试页**（登录用户即可，**不要求 HR 授权**——面试官可无 HR 角色，服务端按本人隔离，非本人 404）：候选人/职位/轮次/时间/状态/反馈截止（逾期标记）/我的反馈；提交反馈 PUT /interviews/{id}/feedback；空态「暂无被安排的面试」。

### 4.4 Offer 与入职交接（抽屉 + /hr/handoffs）

**Offer 对话框**（ADMIN）：
- 版本列表：版本/金额+币种/审批状态（待审批/已通过/已驳回）/状态（草稿/已发送/已接受/已拒绝/已撤回）/时间线/附件（上传/下载/删除）。
- 操作：新建版本（金额/币种/备注）、审批（通过/驳回）、发送、接受（确认文案：指派自动进入已入职并触发交接）、拒绝（备注即原因）、撤回。
- 附件权限：前端仅 ADMIN 可见上传/下载/删除入口；后端下载接口当前为 hr_access_required（与 README「VIEWER 不可下载」不符，待收紧，见 §3.3）。附件大小上限 20MB。

**入职交接页**（ADMIN）：交接配置（CHECKLIST 人工清单 / WEBHOOK 投递 + URL）、记录列表（候选人/职位/部门/手机号/邮箱/状态/尝试/最近投递/失败原因）、失败重试；手机/邮箱列脱敏。

### 4.5 简历语义检索 /hr/search

- 检索区：自然语言输入（占位示例）、模式（自动/混合/向量/整句/技能）、TopK（1–20）、检索（Enter 触发）。
- 结果：候选人姓名（点击跳 /hr/candidates?candidate_id=）、联系方式（脱敏）、技能、分数；展开显示命中段落（无段落说明「结构化/姓名命中」）与元信息（模式/召回与重排耗时等）。
- 检索即审计（SEARCH）；VIEWER 结果脱敏；无模型/失败时明确提示并允许降级。

### 4.6 人事成员 /hr/access（ADMIN）

成员列表（工作区角色 + HR 角色下拉：未授权/查看者/操作员/管理员 + 权限说明）→ 收集变更 →「保存修改」批量提交 PUT /access。

### 4.7 审计日志 /hr/audit-logs（ADMIN）

- 筛选：操作者（工作区成员）、动作、对象类型、时间范围（datetimerange）。
- 表格：时间/操作者/动作/对象类型/对象 ID/结果（成功/失败/拒绝）/补充详情；分页；**只读**。
- 动作枚举（与后端 HrAuditAction 一致）：VIEW_DETAIL / CREATE / UPDATE / ARCHIVE / RESTORE / DELETE / JOB_CLOSE / JOB_REOPEN / ASSIGNMENT_TRANSITION / RESUME_UPLOAD / RESUME_DOWNLOAD / RESUME_DELETE / INTERVIEW_FEEDBACK / OFFER_SEND / OFFER_ACCEPT / OFFER_REJECT / OFFER_WITHDRAW / OFFER_APPROVE / HANDOFF / IMPORT / MERGE / GRANT_ACCESS / REVOKE_ACCESS / EXPORT / SEARCH / ACCESS_DENIED。
- 对象类型（HrAuditObjectType）：CANDIDATE / JOB / ASSIGNMENT / RESUME / HR_ACCESS / OTHER；结果（HrAuditResult）：SUCCESS / FAILED / DENIED。


## 5. 状态机前端约束（PRD §4.3 状态迁移表）

| 源状态 | 前端允许目标 | 交互 |
|---|---|---|
| PENDING_SCREEN | SCREEN_PASSED / 终态 | 拖拽前进直达；终态走对话框+原因 |
| SCREEN_PASSED | INTERVIEWING / 终态 | 同上（可先创建或后补第一轮面试，前端不强制） |
| INTERVIEWING | OFFER / 终态 | 同上；面试反馈**不自动**改状态（前端不联动） |
| OFFER | HIRED / 终态 | HIRED 只能通过 Offer「接受」达成（禁止拖入已入职列） |
| REJECTED | PENDING_SCREEN | 仅 ADMIN 恢复 + 必填原因 |
| WITHDRAWN / CLOSED / HIRED | 无 | 不提供恢复入口；重新参与走新建指派（重投标记） |

- 终态必填受控原因；不得用同一自由文本混用 REJECTED/WITHDRAWN/CLOSED。
- 服务端仍强制状态机，前端规则仅为体验层约束；服务端拒绝时前端必须回滚并展示服务端错误。
- 唯一性约束：同一候选人与同一职位最多一条进行中（PENDING_SCREEN/SCREEN_PASSED/INTERVIEWING/OFFER）关联；「加入职位」/重新指派被服务端拒绝（An active assignment already exists）时，前端原样展示服务端错误，不静默吞掉。

## 6. 接口契约

统一前缀：/admin/api/workspace/{workspace_id}/hr（src/api/hr/recruitment.ts 封装，workspace 取自登录会话）。关键端点：

| 模块 | 端点 |
|---|---|
| 候选人 | GET/POST /candidates、GET/PUT /candidates/{id}、PUT archive/restore/delete、POST check-duplicate、POST /{id}/merge、GET /{id}/resumes、导出、POST /import/candidates + template |
| 简历 | POST /candidates/resumes、GET /resumes/batch-status、GET /resumes/{id}/content、GET /resumes/{id}/flow-logs、GET download、DELETE /resumes/{id}、POST /resumes/search |
| 职位 | GET/POST /jobs、GET/PUT /jobs/{id}、PUT close/reopen、GET /jobs/{id}/matches/{page}/{size}、POST /jobs/{id}/assignments |
| 指派 | PUT /assignments/{id}（status/relation_type/channel/owner_id/note/termination_reason） |
| 面试 | GET/POST /assignments/{id}/interviews、PUT /interviews/{id}、GET /interviews/mine、PUT /interviews/{id}/feedback |
| Offer | GET/POST /assignments/{id}/offers、GET/PUT /offers/{id}、PUT approve/send/accept/reject/withdraw、PUT attachment + DELETE + download |
| 交接 | GET /handoffs/{page}/{size}、POST /handoffs/{id}/retry、GET/PUT /handoff/config |
| AI | GET/PUT /ai/config、POST /ai/search-parse、POST /ai/extract-skills |
| 权限/审计 | GET/PUT /access、GET /access/me、GET /audit-logs |

- 类型契约集中在 src/api/type/hr.ts；标签/枚举/状态常量集中在 src/views/hr/constants.ts（渠道、关系类型、指派/职位/Offer/面试状态、终止原因、流转节点、PIPELINE_ORDER、TERMINAL_STATUSES、格式化工具），**禁止页面内重复定义**。
- 错误处理：统一 MsgError 展示服务端 message；列表加载失败保留旧数据并提示，不白屏。

## 7. 工程与组件规范

- 复用 MaxKB 既有组件（AppTable、AppIcon、通用样式类 p-16-24/flex-between/color-secondary 等）与 Element Plus；不引入新 UI 库。
- 页面职责单一化：候选人/职位页当前为巨石单文件（890/900+ 行），后续按对话框粒度拆分组件（CandidateFormDialog、ResumeListDialog、FlowLogDialog、AssignmentCreateDialog、MergeDialog、ImportDialog、JobFormDialog、InterviewDrawer、OfferDrawer、StatusChangeDialog、AssignmentEditDialog），状态与回调收敛到页面层，常量入 constants.ts。
- 样式：scoped SCSS；看板/卡片等 HR 专属样式以 BEM 风格类名（kanban-col__header 等）组织在页面内，待组件拆分后随组件迁移。
- 文案：当前 HR 页面为中文硬编码；如启用 i18n，全部文案抽 zh-CN/en-US key 并保持枚举标签与 constants 同步。日期统一 toLocaleString('zh-CN', { hour12: false })（或 constants.formatDateTime）。
- 质量门槛：vue-tsc、eslint、vite build（admin）全部通过；涉及 HR 改动须跑通上述三项 + 无头浏览器冒烟（登录 → 各页 → 看板拖拽流转）。

## 8. 非功能要求（PRD §8 映射）

- 列表与基础字段检索 P95 ≤ 2s（10k 候选人/500 职位规模；前端分页 + 条件查询，不做全量拉取）。
- 联系方式/简历内容只按需请求（详情/原文/流转日志均为点开才加载）；VIEWER 全程脱敏。
- 失败反馈：上传/解析/删除/导入/交接重试均有明确成功/失败提示与可重试路径；不产生半成品 UI 状态。
- 审计：前端只触发操作，审计落库由服务端完成；审计日志页只读。
- 可访问性：弹窗可 Esc 关闭、操作有 loading 态、不可逆操作确认框按钮红色样式。
- 浏览器兼容：与 MaxKB 管理台一致（现代 Chromium 系）；小屏（<1200px）菜单仅图标（沿用现有规则）。

## 9. 边界

- **不做**：组织树/员工档案/薪酬/合同/考勤/入职手续（PRD §1）；HR 模块独立登录、独立品牌、独立布局（§1 嵌入定位）。
- **不动**：MaxKB 管理台其他模块前端（知识库/模型/问答/系统设置）与聊天端 SPA。
- **不实现**：AI 自动淘汰/自动发 Offer/自动改状态；跨工作区数据入口。
- 旧版参考 references/agentkb 的 React 页面不参与运行时（PRD §10）。

## 10. 当前实现状态与待办

| 项 | 状态 |
|---|---|
| 7 个 HR 页面与路由/权限显隐 | 已交付 |
| 候选人 CRUD/查重/归档/恢复/删除/合并/导入/导出 | 已交付 |
| 简历上传轮询/列表/原文/下载/流转日志/删除 | 已交付 |
| 职位 CRUD/关闭收尾/恢复/AI 技能抽取 | 已交付 |
| 管道看板（拖拽前进/终态对话框/编辑指派/Offer/面试入口） | 已交付（2026-08-16） |
| 面试安排/反馈、我的面试 | 已交付 |
| Offer 工件（版本/审批/发送/接受/拒绝/撤回/附件） | 已交付 |
| 入职交接（配置/列表/重试） | 已交付 |
| 简历语义检索页 | 已交付 |
| 人事成员授权、审计日志 | 已交付 |
| **表单校验「姓名+至少一种联系方式」（PRD §8）** | 待补（当前仅姓名必填；后端同步门槛未实现） |
| **后端写接口权限收紧**（§3.3：建档/加入职位/传简历/安排面试/面试更新/指派流转 → hr_operator_required；Offer 附件下载按产品口径收紧） | ⚠️ 待办（前端按钮已按角色隐藏，但 API 层 VIEWER 可直调，与 PRD §3 冲突） |
| 巨石页面拆分组件（§7） | 待办 |
| HR 文案 i18n 抽取 | 待办（当前硬编码中文） |
| 候选人列表移动端适配 | 待议 |

## 11. 验收清单

- [ ] 顶栏含「人事部」且其余 MaxKB 菜单不受影响；未授权访问正确拦截
- [ ] VIEWER 全流程脱敏且无受限按钮；OPERATOR/ADMIN 按钮显隐符合 §3 矩阵
- [ ] 候选人表单校验、查重提示、删除/合并确认文案符合 PRD §5.1/§7
- [ ] 看板拖拽与状态机一致：前进成功、回退/跳级/拖入终态被拒并回滚、终态必填原因、恢复仅 ADMIN
- [ ] 简历上传轮询收敛、失败可重传；流转日志六节点完整
- [ ] Offer 接受 → HIRED → 交接记录出现；附件 VIEWER 不可下载
- [ ] 审计日志只读、筛选齐全；越权操作被记录
- [ ] 「我的面试」无需 HR 授权即可访问且仅见本人数据；非本人访问返回 404/无数据
- [ ] VIEWER 直调写接口（POST /candidates、PUT /assignments/{id}、Offer 附件下载等）被服务端拒绝（§3.3 收紧后）
- [ ] vue-tsc / eslint / vite build 通过；无头浏览器冒烟通过

