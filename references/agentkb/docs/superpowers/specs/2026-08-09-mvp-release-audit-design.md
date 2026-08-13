# MVP 发布审查设计

**目标：** 以 PRD、MVP 验收矩阵、简历解析质量评测与搜人质量评测为准绳，对 main 分支实施完整的发布前审查；Critical/Important 发现直接修复并补回归，Minor 记录为发布风险或后续项。

**审查对象：** 当前 main 的后端、前端、数据库迁移、容器运行配置、自动化测试与验收资料。审查不改变产品范围，不尝试补做依赖真实模型凭据和冻结数据集的量化评测。

**审查基线：**
- `docs/PRD.md`：MVP 详细需求、非功能要求、边界。
- `docs/superpowers/specs/2026-08-07-mvp-scope-and-acceptance.md`：P0 功能验收矩阵与发布门槛。
- `docs/superpowers/specs/2026-08-07-resume-quality-evaluation.md`：M3 解析质量评测。
- `docs/superpowers/specs/2026-08-07-search-quality-evaluation.md`：M4 搜人与统计质量评测。

---

## 审查原则

1. 所有结论必须定位到代码、测试、迁移或规格条款；仅凭推测不记为发现。
2. Critical 与 Important 必须先复现，再修复、补回归测试、重跑受影响域；无法复现的项记录为 Minor 或假设。
3. 审查临时脚本仅写入 `/tmp/opencode`，不得污染仓库或作为交付物提交。
4. 不把环境缺失（真实模型 API Key、冻结评测数据集）误报为代码缺陷；它们单独列为 MVP 验收阻塞项。
5. 对所有权限判断验证正向与负向路径，尤其是跨工作区资源、入职员工池与 PII。

---

## 风险域 A：身份、权限与工作区隔离

**范围：** `auth`、`workspaces`、API dependencies、用户/成员模型、候选人与业务资源 API、审计事件。

**核验：**
- access/refresh token 生命周期、Redis 不可用时的受控失败、撤销语义。
- owner/admin/member 权限继承是否符合 PRD F9；member 不得获得管理员写权限。
- 任意跨工作区对象读写均统一 404，避免存在性侧信道。
- hired 池仅 owner/admin 可见；PII 不通过 API、审计、错误消息或搜索卡片泄露。
- 审计事件是否追加式、脱敏且携带必要的 actor/workspace 归属。

**完成标准：** 关键权限路径有自动化回归；无可复现的跨工作区读取、修改或池数量泄露。

## 风险域 B：导入、解析与候选人数据安全

**范围：** 文件上传、解析任务、PII、候选人 revision/override、查重合并、软删除恢复。

**核验：**
- 文件类型、签名、大小、压缩/XML/宏等安全限制与失败清理。
- upload/content-hash/row-hash/run-id 幂等与重试不重复扣费。
- PII 明文只在许可存储位置出现；加密、哈希、出站脱敏与审计一致。
- 重复候选人待审核、合并历史、人工 override 与重新解析不互相覆盖。
- deleted/purged 生命周期、索引清理/恢复和查重可见性一致。

**完成标准：** 无可复现的重复写入、PII 外泄、override 丢失或删除后仍可检索。

## 风险域 C：搜人、统计与模型调用

**范围：** 条件 AST、检索与 rerank、会话上下文、统计查询、模型客户端、出站网关、SSE。

**核验：**
- LLM 输出校验 fail-closed；未知字段、类型、pool scope、统计维度不能转为 500 或 SQL 注入。
- 条件过滤与卡片命中标注口径一致；profile JOIN、学历、数量、无结果、多轮上下文正确。
- `pool_scope ∩ allowed_pool_scopes` 在搜索和统计都在服务端强制，返回、计数、审计不泄露不可访问池。
- 模型失败、rerank 不可用、输出非法、网络异常有预期的降级或受控错误；出站仅经网关。
- SSE 与非流式响应契约、前端解析、会话 context 持久化一致。

**完成标准：** 无 ACL 绕过、静默条件失效、统计误计、SSE 契约断裂或未受控模型失败。

## 风险域 D：招聘流程与数据一致性

**范围：** 职位、HC、指派、状态机、人才池聚合、面试轮、反馈与 offer/hire 闸门。

**核验：**
- 职位 headcount reservation/filled 更新与并发锁；关闭职位和余下指派路径。
- 指派状态机只允许 PRD 转移；终态不可重开；原因和时间线完整。
- 候选人池的 hired/active/rejected 聚合、重指派、入职关闭余下指派在事务和并发下正确。
- interviewing/offer 闸门绑定面试安排与当前轮 recommend 反馈，评分与评语必填。
- 面试官工作区成员校验、反馈 revision/history、AI 总结失败与 overdue 待办的边界。

**完成标准：** 无可复现的超 HC、非法流转、池状态错算、跨工作区面试操作或 offer/hire 绕过。

## 风险域 E：API、前端、迁移与运行部署

**范围：** FastAPI router 契约、React 页面/API 客户端、Alembic、Docker Compose、环境变量、测试/评测执行链。

**核验：**
- API 请求/响应/SSE 与前端类型、路由、操作入口一致；主要 P0 流程可从 UI 到 API 完成。
- 迁移从空库 upgrade head 成功；新增枚举、默认值、索引与 downgrade 边界没有阻断部署的问题。
- 容器与本地运行配置能启动 db、Redis、API、前端；缺失环境变量或 Redis 不可用的行为受控。
- 后端全量 pytest、ruff、前端 vitest/build、`git diff --check` 可重现。
- M3/M4 的真实模型配置、冻结数据集、scorer/CI 是否存在；不存在时明确标为发布验收阻塞，不伪称通过。

**完成标准：** 无迁移或启动阻断、无已实现 UI/API 断链；形成明确的量化验收缺口清单。

---

## 执行与交付

1. 对五个风险域分别审查代码与既有测试，必要时用临时复现脚本验证风险。
2. 发现按 Critical、Important、Minor 分级，包含文件/行号、复现方式、影响、修复建议与对应验收条款。
3. 直接修复 Critical/Important；每项修复附最小回归测试，并重新运行受影响域。
4. 最后执行全量验证：后端 pytest、ruff、前端 vitest/build、迁移升级验证、`git diff --check`。
5. 交付审查报告：已修复项、Minor/已接受边界、MVP 验收矩阵回填、真实模型/评测数据的剩余发布阻塞项。

## 非目标

- 不实现 P1 功能。
- 不提供或猜测真实模型 API Key。
- 不以 mock/placeholder 结果代替 M3/M4 的冻结评测结论。
- 不做与审查发现无关的大规模重构。
