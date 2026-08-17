# 部署验证报告（PRD §8 上线门槛 · 2026-08-17）

> 对照 docs/DEPLOYMENT.md §5「上线前检查表」逐项验证；环境：本机 docker（pgvector/pg16 + redis7 + minio）+ uv 运行。
> 代码基线：v2 分支（含 0025 迁移兜底、D1 screening-v2、498 backend tests 全绿）。

## 验证结论总表

| # | 检查项 | 结论 | 证据 |
|---|---|---|---|
| 1 | Celery worker 就绪探针 | ✅ | worker 启动后写出 worker_ready/worker_heartbeat；探针目录现在由代码自动创建，隔离 Redis DB15 实测 `/tmp/maxkb-worker-isolated` 探针通过 |
| 2 | 任务注册 | ✅（本轮修复） | 显式 imports 增加 `hr.task.agent`；隔离 Redis DB15 worker `ping` OK 且注册 `celery:hr_run_screening_agent` / `hr.task.resume.cleanup_orphan_resumes` |
| 3 | Beat 真实调度 | ✅ | DatabaseScheduler 启动；临时把 crontab 改每分钟 → beat 于 19:00:00 派发，worker received+succeeded 多次；验证后恢复 03:00 每日 |
| 4 | 对象存储私有读 | ✅ | MinIO：签名建桶 200 / 传对象 200 / **匿名 GET 403** / 签名 GET 200（附件/简历需经应用代理） |
| 5 | 备份加密 + 恢复演练 + 轮转 | ✅ | backup.sh：pg_dump→gzip→AES-256-CBC(pbkdf2)；42M 文件头 `Salted__`；正确口令解密/解压后 `pg_restore --list` 637 条目 OK；保留轮转 keep=1 本轮通过 |
| 6 | 日志 PII 脱敏复核 | ✅ | maxkb/drf_exception/unexpected/celery 日志扫描：无真实手机/邮箱/口令（命中为任务耗时、CREATE TABLE 列名等假阳性）；产品层掩码另有测试覆盖（screening 输出 PII 掩码、数据集电话 3****4 掩码、残留 PII 拒入库） |
| 7 | .env 权限 / DEBUG / 密钥不入日志 | ✅ | .env.example 600 权限；settings 默认 DEBUG=False；日志无真实口令/密钥 |
| 8 | PG 连接加密（sslmode） | ✅（本轮补齐） | get_db_setting 新增 MAXKB_DB_SSLMODE 支持 → OPTIONS={'sslmode':'require'}；未设置时为空（无回归） |
| 9 | 租户注销 / 数据返还 / 删除流程 | ✅（阶段 A/B3） | `workspace_offboard` 编排命令 + `WorkspaceOffboardingService`：覆盖 application/knowledge/model/permission/chat/HR 域，预览/脱敏返还包/确认/force/幂等 tombstone/事务回滚/对象存储回收；失败对象进入 `STORAGE_PENDING` 逐对象账本，可由 `workspace_offboard_storage_retry <workspace_id>` 或管理 API 重试并恢复 `COMPLETED`；双工作区 staging-equivalent 回归覆盖完整资源、导出敏感字段扫描和隔离，10 tests OK |
| 10 | Celery worker 探针目录权限 | ✅ | `MAXKB_WORKER_TMP` 可覆盖目录，代码在 ready/heartbeat 时自动 `mkdir -p`；隔离 worker 在目录不存在时直接通过 |

## 本轮补充验收（2026-08-17）

- 本机依赖容器：`maxkb-slim-pg`、`maxkb-slim-redis`、`maxkb-slim-minio` 均运行。
- MinIO 临时 bucket 演练：匿名读 403；删除 `workspace-a/*` 后 `workspace-b/*` 仍可签名读取，最后清理 bucket。
- Celery：隔离 Redis DB15 worker `ping` OK、`celery:hr_run_screening_agent` 已注册、探针文件存在；DB0 实际投递 `cleanup_orphan_resumes` 返回成功。
- 发现并修复：`hr.task.agent` 未在 Celery 显式 imports 中，且探针目录不存在时 ready/heartbeat 失败；均已增加代码和测试覆盖。

## 遗留缺口（上线前须完成）

1. **内核 Workspace 生命周期接入**：本精简内核没有独立 Workspace ORM/删除入口，已交付权威 `workspace_offboard` 命令、callback、系统 API 和 HR 前端页面；后续真实租户平台若有 Workspace 删除事件，应调用该 callback，再编排其它外部域。
2. **真实 staging 注销演练**：本轮已完成本机 staging-equivalent：双工作区完整资源与隔离回归 10 tests、返还包敏感字段扫描、42M 加密备份恢复检查（637 entries）、MinIO 私有读/目标删除/另一工作区对象保留、worker/beat 观测和真实 cleanup task 执行；仍需在实际 staging 编排中重复并由平台验收。
3. HTTPS 终止 / PG 服务端 TLS 证书：为部署编排期配置（gunicorn cert 或 nginx 终止；MAXKB_DB_SSLMODE=require 已可在本仓库配置）。
4. 备份任务进 crontab、月度恢复演练：运维 SOP，非代码项。

## 复现片段

- worker 探针：MAXKB_WORKER_TMP=/tmp/maxkb-worker-probe PYTHONPATH=apps uv run celery -A ops.celery worker -Q celery,model
- beat：uv run celery -A ops.celery beat -S django_celery_beat.schedulers:DatabaseScheduler
- 备份：BACKUP_PASSPHRASE=<独立口令> BACKUP_DIR=<目录> bash installer/backup.sh maxkb 7
- MinIO：见 /tmp/minio_priv_check.py（签名建桶/传对象/匿名403/签名200）
