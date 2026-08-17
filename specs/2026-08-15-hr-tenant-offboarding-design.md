# HR 租户注销 / 数据返还设计（工作区级 HR 数据治理）

> 依据：PRD §7 上线门槛 / docs/DEPLOYMENT.md §5 检查项「租户注销/数据返还/删除流程」。
> 本文件为先决设计稿：给出可落地的数据清单、删除/返还策略、幂等与会话约束。实现排期见验证报告（docs/DEPLOYMENT-VERIFY-2026-08-17.md）。

## 1. 目标与非目标

- 目标：一个 HR 工作区（workspace_id）注销时，可将其在 HR 内的**全部数据**安全清理（默认未加密安全删除；
  可选先导出供数据返还），且全程审计、可幂等重入、可 dry-run 预览。
- 非目标：本文件不覆盖内核其它业务域（application/chat/knowledge 通用知识库/oss 附件）的 workspace 注销；
  只定义 HR 域（hr_* 表 + 简历语义索引 + HR 对象存储）的清理协议，便于内核注销编排时调用。

## 2. HR 数据清单（按依赖序删除）

| 组 | 表/索引 | 依赖上游 | 说明 |
|---|---|---|---|
| 流程账本 | hr_application_event | application | CASCADE 由 application 触发 |
| 子对象 | hr_interview / hr_offer / hr_onboarding_handoff | application | 0025 后挂 application |
| 流程对象 | hr_application | job / candidate | 0025 后唯一挂载点 |
| 流程模板 | hr_job_stage | job | |
| 职位 | hr_job | workspace | 含 close_reason/owner_id 等 |
| 候选人 | hr_candidate / hr_candidate_skill | resume_file | 简历文件先解绑 |
| 简历文件 | hr_resume_file | candidate / document | document_id 指向简历语义索引 |
| Agent 账本 | hr_agent_run / hr_agent_proposal | application/job | 建议随 run 删 |
| 配置/审计 | hr_config / hr_audit_log / hr_access / hr_resume_flow_log | workspace | 最后删 |
| 简历语义索引 | knowledge.Document+Paragraph+Embedding（简历知识库「简历语义索引」下该 workspace 文档） | resume_file.document_id | 须先删文档+向量（delete_resume_index 幂等） |
| 对象存储 | ResumeFile.file_path / 附件（经 hr 存储网关） | — | 按 S3 key 批量删 |

## 3. 命令形态（建议）

    python apps/manage.py hr_offboard_workspace <workspace_id> [--dry-run] [--purge] [--export <dir>]

- 默认行为：审计+清理（physical delete）；`--export` 先输出 JSON 数据返还包（候选/职位/流程/审计摘要）再清理；
- `--dry-run` 只统计不落库（逐表行数、文件 key 数、文档/向量数）；
- 幂等：入口幂等锚点（对一个 workspace 生成一次 offboard 记录，重复执行报已注销）；
- 约束：仅在无人成员在线（或 --force）时允许；先停 Agent 触发（HrConfig.agent_enable_screening 等）再清账本。

## 4. 清理实现要点（代码侧）

- 删除顺序严格按「先子后父、先账本后配置」，用事务包裹；简历文档/向量删除走
  hr/services/resume_index.delete_resume_index（幂等，含 Paragraph/Embedding/Document 级联遗漏补删）。
- 存储文件：enumerate ResumeFile.file_path + 简历原文件 key，经 hr/services/storage 删除（缺失容忍）。
- 导出包结构：{workspace_id, exported_at, candidates, jobs, applications+events, interviews, offers, handoffs, audit}；
  候选人字段脱敏后导出（电话/邮箱掩码），数据返还完成后再清理。
- 审计：写 HrAuditLog(action=EXPORT/DELETE, object_type=OTHER) + 内核注销日志。

## 5. 验收口径

1. 注销后 hr_* 该 workspace 全表归零；简历知识库无该 workspace 文档/向量；存储对象清空。
2. 重复执行幂等（返回已注销，不报错不重复删）。
3. --dry-run 与实际删除计数一致；--export 产出可读 JSON 且导出后清理成功。
4. 不影响其它 workspace（跨工作区数据隔离断言）。
5. 注销全程留痕（EXPORT/DELETE 审计，含执行人/时间）。

## 6. 后续拆分

- 阶段 A：hr_offboard_workspace 命令（如上）——本轮验证报告标注的遗留缺口；
- 阶段 B：内核 workspace 注销编排回调 HR 清理 + 对象存储统一回收；租户数据返还 Web 流程。