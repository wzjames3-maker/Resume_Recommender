# 入职交接设计（B3：Offer 接受后幂等交接至 HRIS/OA/人工清单）

## 背景

PRD §5.3：Offer 接受后关联进入 HIRED，系统生成面向目标 HRIS、OA 或人工流程的交接清单；本产品不创建员工档案；交接失败应可重试且不能重复创建员工记录。PRD §9 定位：产品不是 HRIS/HCM，只负责记录招聘结果并向既有系统或人工流程输出所需信息。

## 范围

### 范围内

- OnboardingHandoff 独立实体：按指派唯一（幂等，不重复建员工）、交接清单 payload、投递目标（CHECKLIST 人工清单 / WEBHOOK 对接 HRIS/OA）、失败可重试、审计。
- 触发：Offer ACCEPTED（B2）事务后自动创建交接记录并投递。
- 配置：HrConfig 增加 handoff_target_type（CHECKLIST 默认 / WEBHOOK）与 handoff_webhook_url。
- 前端：入职交接页面（列表、状态、失败重试）。
- 审计：新动作 HANDOFF（object_type=ONBOARDING，result=SUCCESS/FAILED）。

### 不在范围内

- 真实 HRIS/OA 适配器（以 webhook JSON 协议对接）、重试调度器（当前同步投递 + 手动重试）、员工档案同步。
- 交接内容模板化配置（当前固定清单）。

## 数据模型

### HrConfig 新增字段

| 字段 | 类型 | 规则 |
|---|---|---|
| handoff_target_type | CharField(16) 默认 CHECKLIST | CHECKLIST / WEBHOOK |
| handoff_webhook_url | CharField(512) blank | WEBHOOK 目标 |

### OnboardingHandoff（db_table hr_onboarding_handoff）

| 字段 | 类型 | 规则 |
|---|---|---|
| workspace_id | CharField(64) db_index | |
| assignment | FK(CandidateAssignment, CASCADE) | 唯一（幂等） |
| candidate / job / offer | FK 冗余 | |
| status | CharField(16) 默认 PENDING | PENDING / SUCCESS / FAILED |
| payload | TextField（JSON） | 交接清单（含联系方式，交接场景必须） |
| attempts | PositiveSmallIntegerField 默认 0 | 投递尝试次数 |
| last_error | TextField blank | 最近失败原因 |
| handoff_time | DateTime null | 最近投递时间 |
| user_id / create_time / update_time | | |

约束：UniqueConstraint(workspace_id, assignment_id)。

### payload 固定清单

candidate_id、candidate_name、candidate_phone、candidate_email、job_id、job_name、department、offer_id、offer_version、salary_amount、currency、accepted_at、handoff_created_at。

## 投递语义

- create_handoff_for_offer(offer)：get_or_create(workspace_id, assignment)（幂等）；payload 按上表生成；新记录 status=PENDING。
- deliver_handoff(handoff_id)：attempts+1、handoff_time=now；
  - CHECKLIST：无外部投递，标记 SUCCESS（人工清单即产出）。
  - WEBHOOK：requests.post(url, json=payload, timeout=10)；2xx → SUCCESS；否则 FAILED + last_error。
  - 写审计 HANDOFF（result 对应）。
- accept_offer（B2）事务后同步调用 deliver_handoff（投递为 IO，置于事务外；失败不回溯 Offer 接受）。
- retry_handoff(handoff_id)：仅 FAILED 可重试（PENDING/SUCCESS 400）；调 deliver_handoff。

## API

统一前缀：/admin/api/workspace/{workspace_id}/hr。

| 方法 | 路径 | 权限 |
|---|---|---|
| GET | /handoffs/{current_page}/{page_size} | OPERATOR/ADMIN（列表：候选、职位、状态、尝试、时间；联系方式脱敏展示） |
| POST | /handoffs/{handoff_id}/retry | ADMIN |
| GET | /handoff/config | ADMIN |
| PUT | /handoff/config | ADMIN |

## 前端

- 新页面 hr/handoffs/index.vue + 路由 /hr/handoffs（permission: HR ADMIN）：
  - 表格：候选人、职位、状态 tag、尝试次数、最近投递时间、失败原因 tooltip。
  - FAILED 行「重试」按钮（确认弹窗）。
- api wrapper：getHandoffs / retryHandoff / getHandoffConfig / putHandoffConfig。

## 测试

- 服务层：accept 后自动创建交接（payload 字段齐全）；CHECKLIST 直接 SUCCESS + 审计；WEBHOOK 成功（mock requests.post）；WEBHOOK 失败 FAILED + last_error；重试成功；非 FAILED 重试 400；幂等（同指派重复 accept 不重复建记录）；跨工作区 404；OPERATOR 重试 403。
- 路由层：GET /handoffs 分页；POST retry 200/403；config PUT 校验枚举。
- 回归：既有 255 用例全部通过。

## 验收

HR 全量 PASS、makemigrations 无漂移、ruff 干净、vue-tsc 与双构建 PASS、HANDOFF.md §5.2 B 阶段 Offer/入职交接标记交付。
