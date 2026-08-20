# 生产部署清单（上线前必读）

> 依据：PRD §7 上线门槛；部署项已在本地环境验证（见下）。
> 本文件把验证过的配置固化为上线步骤。

## 1. 前置服务

| 服务 | 要求 | 本机验证 |
|---|---|---|
| PostgreSQL 16 + pgvector | 独立实例或容器；生产建议开启 TLS（sslmode=require）；连接串经 MAXKB_DB_* 配置 | docker maxkb-slim-pg |
| Redis 7 | 生产建议密码 + 独立 DB；支持 Sentinel（CONFIG 已支持） | docker maxkb-slim-redis |
| 对象存储（可选） | S3 兼容（MinIO/OSS/COS）；bucket 私有读；凭据走 MAXKB_S3_* | docker maxkb-slim-minio（已验证私有读 403） |

## 2. 配置（.env）

- 复制根目录 [.env.example](../.env.example) → .env，**chmod 600**。
- 必改：MAXKB_DB_PASSWORD、MAXKB_SECRET_KEY（token_urlsafe 生成）、MAXKB_DEBUG=false。
- 对象存储：MAXKB_STORAGE_BACKEND=s3 + MAXKB_S3_*（本地开发保持 local）。
- worker 探针目录：无 /opt/maxkb-app 写权限时设 MAXKB_WORKER_TMP。
- 密钥管理：DB/Redis/S3 口令只经环境变量注入；BACKUP_PASSPHRASE 建议部署编排单独注入；密钥不得写入日志或代码。

## 3. 启动（生产）

```bash
python main.py start all -d     # gunicorn(web) + celery(worker/beat) + scheduler
python main.py status           # 守护状态
```

- HTTPS：gunicorn 加 --certfile/--keyfile（或前置 nginx 终止 TLS）；本机已验证 HTTPS 生效、明文拒绝。
- 首次启动自动 collectstatic + migrate（含 PG 崩溃恢复重试）。

### 3.1 简历多库迁移核验

本版本新增 0028_resumedatabasemembership。正式环境发布前必须先备份数据库，再执行迁移并检查：

- 每个 workspace 存在一个 ACTIVE 的系统总库，名称为“总库”。
- 每份既有 ResumeFile 至少有一条总库成员关系。
- 总库成员数与 workspace 的 ResumeFile 数量一致。
- 业务库的简历数、候选人数和待解析数通过成员关系去重统计。
- 归档业务库不出现在上传和 RAG 的有效库选择器中。

建议发布后使用一份测试简历执行“总库 + 业务库上传、重复文件跨库归属、库内候选人筛选、库内 RAG 查询”验收，再开放真实 PII。详细规则见 docs/RESUME-DATABASES.md。

## 4. 备份与恢复（已验证闭环）

```bash
BACKUP_PASSPHRASE=<独立口令> BACKUP_DIR=/opt/maxkb-app/backups ./installer/backup.sh maxkb 7
# 恢复演练：
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in <备份>.enc | gunzip | pg_restore -h <host> -U <user> -d <db>
```

- 轮转：默认保留 7 份自然过期；注销租户的数据随轮转清除（见租户注销设计）。
- 建议：备份任务进 crontab，每月做一次恢复演练。

## 5. 上线前检查表

- [ ] Celery worker + beat 真实调度（启动后检查 worker_ready 探针与 django_celery_beat 的 hr-cleanup-orphan-resumes）
- [ ] 对象存储私有读（无凭据访问对象返回 403；附件/简历经应用代理下载）
- [ ] HTTPS 生效且明文端口不开放；PG 连接 sslmode=require
- [ ] 日志脱敏：上线后带真实 PII 走一遍流程，grep 日志目录（maxkb.log / drf_exception.log / unexpected_exception.log）确认无手机/邮箱/口令
- [ ] 备份任务与轮转就绪，恢复演练通过
- [ ] .env 权限 600、密钥未入日志、DEBUG=false
- [x] 租户注销/数据返还流程按 specs/2026-08-15-hr-tenant-offboarding-design.md 落地（含 `STORAGE_PENDING` 失败对象账本与 `workspace_offboard_storage_retry <workspace_id>` 重试）
- [ ] staging 完整注销演练：双工作区隔离、返还包敏感字段扫描、备份恢复、对象存储失败后重试、worker/beat 任务观测
- [ ] 处理真实 PII 前完成以上全部（PRD §7 门槛）

## 6. 已知部署注意点

- installer/ 下 sandbox.c、install_model*.py 为已裁剪能力（ctypes 沙箱/本地模型）的残留文件，**勿使用**。
- main.py 默认 TMPDIR/HF_HOME 指向 /opt/maxkb-app/tmp（可用环境变量覆盖，已 setdefault 化）。
- HR 模块权限独立于工作区成员权限（HrAccess 显式授权），新环境先在人组成员中配置 HR ADMIN。
- 面试/交接/导入接口的并发与批量上限：简历 ≤20MB、导入 ≤200 行/2MB、交接 webhook 超时 10s（同步投递，大批量可后续异步化）。
