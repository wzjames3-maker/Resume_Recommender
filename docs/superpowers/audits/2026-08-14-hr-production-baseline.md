# A 阶段：生产基础补齐验收基线

> 依据：`docs/PRD.md`（第 3、7、9 节上线门槛与 A 阶段完成定义）及以下规格：
> - `docs/superpowers/specs/2026-08-14-hr-process-model-design.md`（A2 流程模型）
> - `docs/superpowers/specs/2026-08-14-hr-access-audit-design.md`（A3 访问控制与审计）
> - `docs/superpowers/specs/2026-08-14-hr-lifecycle-design.md`（A4 生命周期与简历治理）
>
> 执行环境：主目录 `/home/wzjames/toC/maxkb`，分支 `v2`。配置：`MAXKB_CONFIG_TYPE=ENV` + `MAXKB_*`（本地 docker PostgreSQL 16/pgvector 于 127.0.0.1:5432，Redis 7 于 127.0.0.1:6379）。

## 完成定义逐项核对（PRD 9.2 A 阶段）

| 完成定义项 | 状态 | 证据 |
|---|---|---|
| 显式 HR 授权（查看者/操作员/管理员） | ✅ | A3：`HrAccess` 模型、`hr_access_required`/`hr_admin_required` 装饰器、`GET/PUT /hr/access`；VIEWER 脱敏 |
| 负责人与待办队列 | ✅ | A2：`Job.owner_id`/`Assignment.owner_id`、`owner_id` 筛选、「待我处理」快捷视图 |
| 职位暂停/关闭可收尾 | ✅ | A2：`DRAFT/ON_HOLD/CLOSED`、`close_reason`、`PUT /jobs/{id}/close` 批量收尾、`reopen` |
| 来源、告知、处理依据和联系偏好可采集、校验和审计 | ✅ | A4：`source_type/source_detail/collected_at/consent_status/consent_version/contact_preference` |
| 待识别简历 30 天清理，已关联简历与删除/匿名化联动 | ✅ | A4：`cleanup_orphan_resumes` Celery 任务（daily beat）、`delete_candidate` 删除简历文件与记录 |
| 第 7 节所有上线门槛经部署验证 | ⚠️ 部分 | 见下「部署环境验证项」；本机无法完整验证项明确列出 |

## 全量回归（2026-08-14）

| 命令 | 结果 |
|---|---|
| `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb` | 227 tests，OK（首次跑出现 2 个瞬态错误，系测试库缺 0009 迁移所致；迁移应用后复跑两次均 OK） |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `manage.py migrate --check` | exit 0（无未应用迁移） |
| `manage.py check` | System check identified no issues |
| `ruff check apps/hr/` | All checks passed |
| `vue-tsc --build`（ui/） | PASS |
| `vite build` / `vite build --mode chat`（ui/） | ADMIN_OK / CHAT_OK |

## A1-A4 交付与审查

| 子任务 | 提交 | 测试 | 审查结论 |
|---|---|---|---|
| A1 流程口径 | `41e34af` | +4（99→…） | 归档拦截与 HC 统计改用 `ACTIVE_ASSIGNMENT_STATUSES`；候选人详情接入 |
| A2 流程模型 | `5e5c1ad`、`9226fa1`、`c675393` | +42（→141）；修复 +8 | 审查 3 Major（owner_id 500、edit_job 绕过关闭语义、建关联 TOCTOU）已修复 |
| A3 访问控制与审计 | `92a8cff`、`83782e8` | +42（→183） | HrAccess/HrAuditLog、脱敏、审计埋点、成员/审计页面 |
| A4 生命周期 | `4443106`、`5be40f9`、`7419727` | +24（→207）；修复 +8（→215） | 审查 2 Major（CSV 公式注入、DELETED 可复活）已修复 |

## 部署环境验证项（本机未完整验证，须在真实部署完成）

| 项 | 要求 | 本机状态 |
|---|---|---|
| Celery worker 与 beat 真实调度 | TTL 每日任务与简历解析任务在 worker 中运行 | 受限：worker heartbeat 硬编码 `/opt/maxkb-app/tmp`（需 sudo）；任务函数已同步调用测试覆盖 |
| 对象存储/简历文件权限 | 私有读、按租户与对象授权 | 本机文件系统；生产须私有对象存储 |
| 传输与静态加密 | TLS、数据库/备份/对象存储静态加密、密钥不落日志 | 依赖部署环境，未验证 |
| 日志/监控脱敏人工检查 | 手机/邮箱/简历内容不出现在普通日志与监控标签 | 未验证 |
| 备份保护与删除流程 | 备份自然过期、删除/匿名化后备份清理边界 | 未验证 |
| 租户注销与数据返还/删除 | 企业协议层流程 | 未验证（PRD 标注部署协议层） |

## 已知限制

- 面试官仍为文本字段；候选人「更正请求」由编辑 + 审计承接，无独立审批流。
- 批量导入 CSV、完整 Offer 工件、入职交接、语义检索属 B/C 阶段。
- 导出为固定字段白名单 CSV（不含联系方式），非可配置导出。
- 未关联简历清理为每日调度，30 天窗口内存在最多约 24 小时延迟。

## 结论

A 阶段核心完成定义已满足：显式授权、负责人与待办、职位收尾、合规元数据、简历 TTL 与删除联动均落地且有自动化测试（215 个 HR 用例 + 12 个内核回归）。处理真实候选人 PII 的部署环境验证项（TLS、静态加密、对象存储权限、日志脱敏、备份/租户注销）需在目标部署环境完成后方可正式导入真实数据。
