# 生产级就绪度分析 — MaxKB 精简内核 + HR ATS 工作台

> **[已归档]** 本分析基于 2026-08-20 基线 `58075ce`，其中 P0/P1 缺口已由 2026-08-22 全项目代码审查（`docs/archive/CODE-REVIEW-2026-08-22-FULL.md`）及其后续 P2/P3 修复批次落地；现役口径以 `docs/PRD.md` + `HANDOFF.md` 为准。仅作历史路线参考。

> 目标：回答「当前项目是什么、开发者想做什么、距离生产级还差什么」  
> 基线：`v2` 分支 HEAD `58075ce`（2026-08-20），未提交改动 54 文件 + 0027-0029 迁移待提交  
> 评估口径：PRD §7/§8 上线门槛 + `DEPLOYMENT.md` + `HANDOFF.md` §4 + 12-factor / SRE 常规检查

---

## 0. 一句话结论

**这不是通用知识库二次开发，而是一个「借 MaxKB 壳、做轻量 ATS」的垂直 HR 产品**：保留 MaxKB v2 的认证/工作区/模型网关/向量检索内核，砍掉工作流/MCP/沙箱/本地模型等重资产，在 `apps/hr` 里自建了一套**传统 ATS 底座（Application + JobStage + Pipeline）+ 简历 RAG（pgvector+tsvector → RRF → rerank → Small-to-Big）+ Propose-Confirm-Execute Agent 运行时**。A/B/C/D 阶段的功能闭环已在代码与测试层面完成（HR 512 tests、后端 511+ 全量回归），但**生产化属于「功能就绪、工程未就绪」**：真实部署、密钥/加密、观测、可扩展、数据治理、合规法律仍有 P0 级缺口，未达到 PRD §8「可处理真实候选人 PII」的门槛。

---

## 1. 当前项目是什么

### 1.1 技术栈与形态

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.11 / Django 5.2 / DRF / drf-spectacular | 单体，`main.py` 统一入口（`dev`/`start`/`upgrade_db`/`collect_static`），`apps/` 挂 `sys.path`，`CONFIG` 单例（`MAXKB_CONFIG_TYPE=ENV` 或 `/opt/maxkb/conf` YAML） |
| 前端 | Vue 3 / Vite / Element Plus / pnpm | 双 SPA：admin（管理后台）+ chat（嵌入对话），`ui/dist` 由 Django 静态服务，`ui/env/` 多环境，Vite 代理 `/admin/api`、`/chat/api` → `:8080` |
| 数据 | PostgreSQL 16 + pgvector + pg_trgm / Redis 7 / Celery + celery-once + django-celery-beat + django-apscheduler | 双队列 `celery`/`model`，hmac 签名序列化，Redis 支持 Sentinel |
| 存储 | `LocalStorage`（开发）/ `S3Storage`（MinIO/OSS/COS，`MAXKB_S3_*`） | key 含 workspace 前缀，私有读经应用代理，S3 删除失败落 `WorkspaceOffboardStorageCleanup` 账本重试 |
| 模型 | OpenAI 兼容单一 Provider (`openai_model_provider`) | LLM `sensenova-6.8-flash-lite` / Embedding `BAAI/bge-large-zh-v1.5` / Rerank `BAAI/bge-reranker-v2-m3`，类型 `LLM`/`EMBEDDING`/`RERANKER` |
| 部署 | `gunicorn` + `celery worker/beat` + `scheduler`（`main.py start -d` 守护）/ Docker 三件套 `maxkb-slim-pg/redis/minio` | `installer/` 含 `backup.sh`（pg_dump→gzip→AES-256-CBC pbkdf2）、`production_landing.sh` |
| 包管理 | 后端 `uv` / 前端 `pnpm` | `ruff`（120 列）、`vue-tsc`、`eslint` |

### 1.2 目录与关键模块

```
apps/
  maxkb/settings/base/web.py   # 单一 settings（DB/cache/INSTALLED_APPS/STATIC）
  maxkb/const.py + conf.py     # CONFIG 单例、get_db_setting/get_cache_setting
  users / knowledge / application / chat / models_provider / system_manage / common / ops
  hr/                           # ★ 人事工作台（核心增量）
    models/recruitment.py       # Candidate/Job/Application/JobStage/ApplicationEvent/Interview/Offer/Handoff/
                                # ResumeFile/ResumeDatabase/Membership/ResumeFlowLog/HrAccess/HrAuditLog/
                                # HrAgentRun/HrAgentProposal/HrOffboard + HrConfig
    services/                   # 16 个 service：resume_parser/splitter/index/search/storage/
                                # application_service/knowledge_search/similar_jobs/query_understand/
                                # ai_parser/flow_log/audit/offboarding/agent_workbench/agent_stats
    agents/                     # Agent 运行时：runner/base/copilot_runner/draft_runner/sourcing_runner/
                                # scoring/context/proposals/scope
    views/ + serializers/ + urls.py  # 60+ 端点（/workspace/{ws}/hr/*）
    migrations/0027-0029        # 总库多库 + raw_text
    task/resume.py              # parse_resume_task / cleanup_orphan_resumes
ui/src/views/hr/
  pipeline / dashboard / candidates / resumes / jobs / interviews / my-interviews /
  agents / search / offers / handoffs / audit / access / offboarding
docs/
  PRD.md / ATS-STATE-MACHINE-V2.md / PRD-AGENT-RAG.md / RAG-V2-DESIGN.md /
  RESUME-DATABASES.md / DEPLOYMENT.md / HR-FRONTEND-GUIDE.md / screening-eval-*.md
```

### 1.3 URL 与权限面

- 管理面 `/admin/api/*`（users/models_provider/folders/knowledge/system_manage/application/oss + `workspace/{ws}/hr/*`）
- 对话面 `/chat/api/*`（chat_api / chat_authentication_api / chat_embed_api / vote_api，MCP 已移除）
- 鉴权：`common.auth.authenticate.AnonymousAuthentication` + HR `hr_access_required/hr_operator_required/hr_admin_required` 三档（`HrAccess` 显式授权，`VIEWER` 联系方式脱敏，`OPERATOR` 可操作，`ADMIN` 可管理）
- 审计：`HrAuditLog` 只增不改（VIEW_DETAIL/CREATE/UPDATE/ARCHIVE/BULK_IMPORT/OFFER_* + AGENT_RUN/AGENT_DECIDE + ACCESS_DENIED，含 `trace_id` 链路）
- 租户隔离：所有 HR 资源持久化 `workspace_id`，服务端从认证主体派生，不信任 URL 参数，跨 workspace 统一 404

### 1.4 交付状态矩阵（事实，非规划）

| 域 | 状态 | 关键证据 |
|---|---|---|
| RAG v2（简历语义） | ✅ 已交付 | LLM 切片（PII 掩码前置→行号边界→L2 校验→规则降级）→ `resume_index` 三副本（dense=`title\ncontent` 的 chunks / sparse=tsvector+Termbase / 结构化）→ `search_resumes` 双路召回→RRF(k=60)→bge-reranker-v2-m3→Small-to-Big；12 锚点 recall@5=0.92 / MRR=0.785；`resume_database_ids` 多库贯穿全链路 |
| ATS v2 重构 | ✅ 已交付 | `Application + JobStage + ApplicationEvent`（stage 与 status 分离），`ApplicationStatus=ACTIVE/HIRED/REJECTED/WITHDRAWN/CLOSED`，唯一约束 `(workspace,candidate,job,ACTIVE)`，迁移 0025 含 CandidateAssignment→Application 数据兜底（ApplicationEvent IMPORTED 幂等锚点） |
| 招聘协作 | ✅ 已交付 | Job 两阶段关闭 STRICT/BULK + Interview/Offer/Handoff 挂 Application + Offer 接受联动 HIRED 幂等交接 + 批量导入（≤200 行/2MB）+ 全局/我的面试双视图 |
| 简历多库 | ✅ 已交付 | 0027/0028：`ResumeDatabase`（系统总库 `is_system` + 业务库）+ `ResumeDatabaseMembership` 多对多；SHA-256 去重复用；归档隔离；前端 `/hr/candidates` 总览 → `/hr/resumes/databases/:id` 库内详情 |
| Agent D1-D4 | ✅ 已交付（首版） | D1 Screening（事件/人工触发、celery-once 防重、并发2/限速10/h、LLM 失败降级 FAILED、服务端评分派生 ADVANCE/DECLINE/HOLD、Proposal 审批）、D2 JD 起草+Interview Copilot（知识库白名单 `agent_knowledge_bases`）、D3 Sourcing+沟通草稿、D4 工作台（运行记录/tool_trace/Token/失败重试/Proposal 收件箱/证据链/段落原文抽屉/跨页 summary） |
| 评测 | ✅ 基线完成 | `import_resume_dataset`（300 简历）+ `eval_screening`（200 例正负配对，4 并发真实 LLM）；screening-v2 82.5% 宽松一致率达成 ≥80%（负 100% / 正 65%，残留为 flash-lite 数值标定）；全量回归 HR 500+ tests |
| 租户注销 | ✅ 阶段 A/B1/B2/B3 交付 | `hr_offboard` tombstone（0026）+ `WorkspaceOffboard` 跨域 tombstone + `workspace_offboard(_storage_retry)` 命令 + 系统 API + HR 前端注销页 + `STORAGE_PENDING` 逐对象账本；双工作区 staging-equivalent 演练通过 |
| 部署验证 | ✅ 本机验证完成 | `DEPLOYMENT-VERIFY-2026-08-17.md`：worker/beat 调度、对象存储 403/签名 200、备份 42M Salted__+637 entries 恢复、日志 PII 扫描无泄露、.env 600 / DEBUG=False、PG sslmode |

> **注意**：上表「已交付」指功能与自动化测试就绪，不等于 `PRD §7` 生产上线门槛已满足（见 §3）。

---

## 2. 开发者的意图（推演）

### 2.1 为什么 fork MaxKB 而不是从零做 ATS

- **复用内核资产**：认证/工作区/模型网关/向量检索/对象存储/Celery 基础设施已成熟，避免重造；项目自述「MaxKB v2 精简内核 + 多租户 HR 工作台」。
- **做减法**：上游工作流引擎/MCP/函数库/多模态/本地模型被**物理删除**（见 `CLAUDE.md`），保持单体可控与 GPL-3.0 合规。
- **定位轻量 ATS 而非 HRIS**：PRD §1 明确「不是 HRIS/HCM，不建组织树/薪酬/合同/考勤」，只做 `Workspace → ResumeDatabase → Candidate → Application → JobStage → Interview/Offer/Handoff` 闭环，Offer 后输出交接清单即止。

### 2.2 产品哲学（四条底线）

1. **招聘需求优先**：`Job` 是可执行需求≠职位目录；流程挂在 `Application`（候选人×职位关系）而非候选人档案。
2. **数据最小化**：PRD §2.2/§7 自由文本禁身份证/银行/健康/宗教/婚育；RAG 默认不送联系方式/备注/原文；`HrAuditLog` 全量留痕。
3. **人工决策优先 → 工程化为 Propose-Confirm-Execute**：AI 只写 `HrAgentProposal`，人审批后走 `Application` 命令（`move_stage`/`terminal`/`restore`），`ApplicationEvent` 不可变账本；高分自动推进仅 D3 经数据论证后按分带开放。
4. **先安全后扩展**：PRD §7 明确未达上线门槛前**不得处理真实 PII**，先用脱敏/测试数据。

### 2.3 架构裁决（刻意不做什么）

| 议题 | 决策 | 理由 |
|---|---|---|
| 编排框架 | Django + Celery + 信号，不引入 LangGraph/FastAPI 编排 | 单体已含异步/防重/定时/审计；MaxKB flow 引擎已删除不回引；中心化可控 |
| 向量库 | pgvector+tsvector 双路，不建 Milvus/ES | 试点 10k 候选人未到瓶颈；检索已达标 0.92 |
| 职位库 | SQL 相似 + HIRED 画像，不建向量库 | 500 职位无需向量化 |
| 知识库 | **直接复用 MaxKB 工作区知识库**（企业 JD 模板/题库/FAQ），不另建 | 这是相对参考架构的天然优势；简历语义索引用 `hr_protected` 隔离 |
| 调度/外发 | 调度（日历集成）、候选人端自动外发、Offer 定价均**不做** | 内部工作台定位 + 无渠道集成 + 与 §2.2 冲突；外发永远人工 |
| 沙箱 | ctypes 沙箱删除，仅留 Jinja2 SandboxedEnvironment | 降低攻击面 |
| 模型 | 单一 OpenAI 兼容 Provider，起步单档 flash-lite，档位对比待定 | 接入成本低；run 表已记 token 成本可演进 |

### 2.4 路线设计（PRD §9.2 + PRD-AGENT-RAG §12）

- **R1-R5**：ATS v2 底座与协作闭环（已完成，419→419+）
- **A**：生产基础补齐（HR 显式授权/审计/生命周期/30 天 TTL）
- **B**：面试/Offer/交接/批量导入
- **C**：语义检索与可解释匹配（已完成，RAG v2）
- **D1**：Agent 运行时 + Screening（首个 100% 复用 RAG 的 Agent）
- **D2**：JD 起草 + Interview Copilot（企业知识库白名单）
- **D3**：Sourcing 激活 + 沟通草稿 + 反馈闭环/采纳率 + 免审分带论证
- **D4**：Agent 工作台首版（已实现，待补跨页指标/原文定位/反馈重试表单）

### 2.5 文档与治理风格

- 权威顺序：`ATS-STATE-MACHINE-V2.md`（目标） > `PRD.md`（意图） > `PRD-AGENT-RAG.md`（智能化） > `ATS-DESIGN-SPEC.md`（现状快照，仅迁移对照） > `RAG-V2-DESIGN.md`
- 测试即规格：HR 500+ 用例覆盖状态机/权限/PII/降级/多库/注销
- 运维要点显式化：`vite build` + `collect_static` + 重启 Django 才使 8080 生效（`is-hr-main .el-dialog` 弹窗、`/admin/hr/*` base 路径等教训已沉淀）

---

## 3. 距离生产级还差什么

> 按 **P0 上线阻塞 / P1 上线后 30 天 / P2 演进** 分级；每项含现状、风险、验收标准。

### 3.1 安全与合规（PRD §7 是门槛，当前最短板）

**P0**
- [ ] **真实部署全链路 TLS**：gunicorn cert 或 nginx 终止 + `MAXKB_DB_SSLMODE=require` 服务端证书校验（当前仅代码侧 OPTIONS 已就绪，部署侧未落地）
- [ ] **静态加密**：DB 磁盘加密 / 对象存储 SSE / 备份 `BACKUP_PASSPHRASE` 独立于 DB 口令且走部署编排注入（勿进 `.env` 明文）
- [ ] **密钥管理**：`SECRET_KEY`/`DB_PASSWORD`/`S3`/`SENSENOVA_API_KEY`/`SILICONFLOW_API_KEY` 全经环境变量/secret 管理器，**永不入库、永不落日志**（`api.txt` 等测试 key 已在 `.gitignore`，需持续审计）
- [ ] **PII 全链路脱敏验证**：`HrAgentRun.tool_trace/input_meta`、`maxkb.log/drf_exception.log/celery-run.log`、`HrAuditLog.detail` 均已规则脱敏，需**带真实 PII 走全流程后 grep 复核**并产出报告（DEPLOYMENT-VERIFY 已做本机扫描，生产需重做）
- [ ] **附件与对象存储私有读**：匿名 403 / 签名 200 已在本机 MinIO 验证，生产需对 S3 bucket 策略 + 应用代理下载链路做渗透复核
- [ ] **HR 显式授权落地**：新环境首次初始化 `HrAccess`（内核 `get_user_members` 精简部署回退逻辑已修 `hr_members`，需在生产人组成员中配置 ADMIN，避免 VIEWER 越权）

**P1**
- [ ] **审计不可变与留存**：`HrAuditLog` 只增不改已满足，需补**不可删除/不可改写**的 DB 约束或 WORM 存储 + 按 `trace_id` 关联 `HrAgentRun`→`Proposal`→`ApplicationEvent` 的 SIEM 检索
- [ ] **权限回归自动化**：VIEWER 脱敏 / OPERATOR 越权 / 面试官最小可见（仅本人面试 + 无 PII）的负向用例已在测试中，生产需在 staging 跑完整权限矩阵并留存证据
- [ ] **依赖漏洞扫描**：`psycopg[binary]==3.2.9 / cryptography==50.0.0 / minio>=7.2.20` 等需进 `pip-audit`/`trivy` 流水线

**P2**
- [ ] **数据分类分级与 DPA**：PRD §7 要求的来源/告知/处理依据/联系偏好/保留策略/租户注销 DPA 文本（本 PRD 声明「不替代法律意见」）

### 3.2 数据与生命周期

**P0**
- [ ] **备份与恢复 SOP 固化**：`installer/backup.sh` 已验证 42M 加密备份 + `pg_restore 637 entries` 恢复，生产需进 `crontab`（每日）+ **月度恢复演练**并产出 RTO/RPO 报告；保留 7 份轮转需与租户注销「随轮转清除」对齐
- [ ] **未关联简历 30 天 TTL**：`cleanup_orphan_resumes` 已注册 beat（03:00），需在生产验证真实调度与 `ResumeFlowLog` 留痕
- [ ] **迁移可逆与演练**：0025（CandidateAssignment→Application，DEFERRABLE + `SET CONSTRAINTS ALL IMMEDIATE`）/0028（总库多库）/0029（`raw_text`+pg_trgm）在 staging 先**备份-迁移-回滚**演练

**P1**
- [ ] **candidate_skill 回填与 Termbase 重嵌**：`production_landing.sh` 四步（migrate→backfill→seed Termbase→reindex）需在低峰窗口执行；重嵌期检索降级为 seq scan，需观测 QPS 与 P95
- [ ] **数据质量**：`Candidate` 当前仅强制 `name` 必填（PRD §4.1/§8 要求 name+联系方式），需在服务端补校验；解析失败的待识别简历不得进入筛选流程

**P2**
- [ ] **保留与删除策略产品化**：归档/恢复/到期删除/候选人撤回/更正/争议保留的配置化与审计

### 3.3 可用性与运维

**P0**
- [ ] **staging 真实注销演练**：双工作区隔离、返还包敏感字段扫描、`STORAGE_PENDING` 失败→重试恢复、MinIO 目标删除/另一租户保留、备份恢复、worker/beat 观测（本机 staging-equivalent 已通过 10 tests，生产 staging 需重跑并由平台验收）；外部 Workspace 生命周期需对接 `WorkspaceOffboardingService`/`workspace_offboard` callback
- [ ] **进程与探针**：`main.py start all -d` 守护 + `worker_ready/worker_heartbeat` 探针（`MAXKB_WORKER_TMP` 自动 `mkdir -p` 已修）需接**存活/就绪探针与告警**（当前仅文件探针，无 HTTP 健康检查）
- [ ] **发布原子性**：前端 `vite build` + `collect_static` + 重启 Django 的**必做清单**（`STATIC_ROOT=apps/static`、8000 vs 3000 双端口 hash 校验教训）进发布手册

**P1**
- [ ] **日志与轮转**：`MAXKB_LOG_DIR=/opt/maxkb-app/logs` + `logs/celery-run.log` 需 logrotate / Loki / ELK 转发；`maxkb.log` 2.1M 已见，需限大小与级别
- [ ] **Celery 可观测**：`hr_run_screening_agent` 的 P95 ≤30s、排队深度、失败率、concurrency 2 的限流是否瓶颈需 dashboard；当前仅 `logs/celery-run.log` 文本
- [ ] **DB 连接池与超时**：`dj_db_conn_pool` + `MAXKB_DB_MAX_OVERFLOW=80`/`MAXKB_REDIS_MAX_CONNECTIONS=100` 需按 50 并发/10k 候选人/500 职位压测调参；Offer webhook 10s 同步投递，大批量需异步化

**P2**
- [ ] **多实例与水平扩展**：当前单机三容器（pg/redis/minio）+ 单 gunicorn + 单 worker，生产需无状态化与共享存储验证

### 3.4 性能与可扩展

**P0**
- [ ] **P95 ≤2s 验收**：PRD §8 要求 10k 候选人/500 职位/50 并发下 候选人列表/检索/职位关联列表 P95 ≤2s（当前仅功能正确性测试，无压测报告）
- [ ] **检索语义质量**：已做 12 锚点 recall@5 0.92，但需**分类型 30+ 标注集**（lookup/conditional/browse/skill-AND）+ 消融评测（title 入 chunks 前后 / L1 预筛前后 / λ 调参），且 `conditional` 类条件精确率必须 1.0（SQL 保证）

**P1**
- [ ] **索引与查询优化**：`document_id` 过滤（`resume_search.py:103` 自建 query_set）+ `pg_trgm GIN(raw_text)` + `hr_agent_run(ws_type_status)` 等索引需 `EXPLAIN ANALYZE` 复核；N+1 已用 `select_related` 治理，需持续 `django-debug-toolbar` 扫描
- [ ] **重嵌与回填成本**：`_split_pieces` ≤100 字子段 + `_batch_save` 的 embedding 并发与 DB 写入需限流与断点续传

**P2**
- [ ] **模型分级**：flash-lite 数值标定导致正样本误拒（64% 召回），需更强档位对比与阈值冻结（80/60 分带）经独立标定集或 5 折交叉验证

### 3.5 质量与测试

**P0**
- [ ] **未提交改动清零**：当前 `git status` 54 文件 modified + 0027-0029/missing tests 未入 HEAD，**禁止带脏工作区发布**；`makemigrations --check --dry-run` / `migrate --check` / `ruff` / `vue-tsc` / `vite build` / `collect_static` 必须全绿（HANDOFF 已记录 511 tests OK 基线，需在干净 HEAD 重跑）
- [ ] **真实 LLM 探针**：`hr_agent_probe`（`RUN_REAL_MODEL=1`）与 `installer/resume_splitter_dataset30.py` 的 30 例内容保真/LLM 路径/PII 扫描需进 CI 定时任务

**P1**
- [ ] **CI 流水线**：`uv run python manage.py test hr.tests application.tests knowledge.tests models_provider.tests ops.tests common.tests --keepdb` + `ruff` + `vue-tsc` + `eslint` + `vite build` + `trivy` + 部署验证脚本的 GitHub Actions
- [ ] **契约测试**：`HrResumeSearchAPI` / `AgentRunAPI` / `ApplicationMoveStageAPI` 的 OpenAPI 快照与前端 `hr.ts` 类型对齐

**P2**
- [ ] **混沌与故障注入**：embedding/rerank/LLM/S3 任一失败的降级链（rerank→RRF→dense→空结果+meta）需故障演练

### 3.6 部署与基础设施

**P0**
- [ ] **环境一致性**：`MAXKB_CONFIG_TYPE=ENV` + `.env.example → .env (600)` + `uv.lock`/`pnpm-lock.yaml` 锁定；`installer/Dockerfile*` 的 `sandbox.c`/`install_model*.py` 为已裁剪残留，勿用
- [ ] **配置校验**：`_env_float/_env_int` 已对 `MAXKB_HR_EVIDENCE_LAMBDA` 等非法值回退并告警，需在启动时**显式校验必填项缺失即失败**

**P1**
- [ ] **12-factor 完善**：`TMPDIR/HF_HOME` → `/opt/maxkb-app/tmp`（`setdefault` 化）+ `MAXKB_WORKER_TMP` + `MAXKB_LOG_DIR` 的目录权限与持久化
- [ ] **镜像与供应链**：`Dockerfile-base` / `Dockerfile-vector-model` 的基础镜像锁定与 SBOM

**P2**
- [ ] **多环境**：`dev`（`main.py dev web/celery` 双终端）/ `staging` / `prod` 的配置与数据隔离策略

### 3.7 前端与体验（已做多轮打磨，剩余为收口）

- 已修复：弹窗遮挡（`is-hr-main .el-dialog` flex+max-height）、表单 label 覆盖（`el-form--label-top` 收窄）、SPA base（`./` → `ENV.VITE_BASE_PATH`）、字段名不匹配（`assignments` vs `applications`）、成员空回退（`hr_members`）、重复入口收敛、技能 `raw_text/paragraph` 回退
- **P1**：`ui/src/views/hr/jobs/index.vue` 1700 行、`candidates/index.vue` 978 行的**拆分与单测**；`vite build` 产物 hash 校验进发布检查；`SimpleLayout` 的 HR 二级导航与响应式样式需在 1366×768/1280×720 真机回归

### 3.8 Agent 与模型

- 已交付：白名单工具只读、PII 上下文投影、Prompts `screening-v2` 版本化、`HrConfig` 开关默认关、并发/限速护栏、失败零影响
- **P1**：D3 免审分带（若开放）需经 ≥80 例标定集数据论证 + ADMIN 显式开启 + 审计与回滚；`tool_trace` 的 PII 与 `prompt_tokens/completion_tokens` 成本报表需进 dashboard 告警阈值
- **P2**：多模型路由（strong/weak）与 `agent_prompt_versions` 的灰度

### 3.9 租户与数据主权

- B3 的 `STORAGE_PENDING` + `workspace_offboard_storage_retry` + `GET/POST /admin/api/workspace/{id}/offboarding/storage` 已闭环对象存储失败重试
- **P0**：GPL-3.0 继承合规（`LICENSE`）与商业分发时的源码提供义务
- **P1**：`WorkspaceOffboard` 跨域编排（application/knowledge/model/permission/chat/HR）与外部租户平台事件的**幂等对接**（`preview/export/offboard` callback contract 已定义）

---

## 4. 下一步路线图（建议，按优先级）

### 4.1 本轮内可闭合（1-2 周，冲刺 P0）

1. **冻结干净基线**：提交 54 文件 + 0027-0029（含 `raw_text` pg_trgm 索引）→ 在干净 HEAD 重跑 `511 tests + ruff + vue-tsc + eslint + vite build + collect_static + migrate --check` 并归档报告
2. **staging 一键部署**：按 `DEPLOYMENT.md` + `.env.example` 在 staging 拉起 pg/redis/minio + gunicorn/celery/beat，跑通 `DEPLOYMENT-VERIFY` 10 项检查表并产出带证据的报告
3. **带真实 PII 的全链路脱敏复核**：走一遍 上传→解析→检索→Screening→面试→Offer→注销，grep 全日志目录确认无手机/邮箱/口令
4. **备份/恢复月度演练首轮**：`BACKUP_PASSPHRASE` 独立注入 → `backup.sh` → `openssl enc -d | gunzip | pg_restore --list 637` → 文档化 RTO/RPO
5. **P95 冒烟压测**：10k 候选人（复用 `import_resume_dataset` 300 的扩展）+ 50 并发 `k6` 压候选人列表/检索，产出 P95 报告，不达标则优化索引/连接池
6. **密钥与权限基线**：`.env 600` / `DEBUG=false` / `SECRET_KEY` 随机 / `HrAccess` 初始化 / S3 私有读 403 复核

### 4.2 上线后 30 天（P1）

- CI/CD + 镜像供应链 + 日志/指标/告警（探针→HTTP 健康检查、Celery 队列深度、检索 P95、Agent 失败率）
- 权限矩阵与审计的 staging 回归自动化与存档
- `production_landing.sh` 低峰重嵌与 Termbase 词条固化
- D3 免审分带的标定集（≥80 例）冻结与 ADMIN 受控开放

### 4.3 演进（P2）

- 水平扩展与多实例一致性验证
- 强模型档位对比与阈值重标定（解决正样本 65% 召回瓶颈）
- 数据保留策略产品化与 DPA 法务文本
- GraphRAG/ColBERT 等重型检索的**不做**决策复核（保持 pgvector 够用即不引入）

---

## 5. 关键文件索引

| 问题 | 去哪里看 |
|---|---|
| 产品意图 | `docs/PRD.md` §1-§2 + `docs/ATS-STATE-MACHINE-V2.md` |
| 现状快照 vs 目标 | `docs/ATS-DESIGN-SPEC.md`（现状） vs `ATS-STATE-MACHINE-V2.md`（目标） |
| RAG 细节 | `docs/RAG-V2-DESIGN.md` + `apps/hr/services/resume_search.py` / `resume_splitter.py` / `resume_index.py` |
| Agent 细节 | `docs/PRD-AGENT-RAG.md` + `apps/hr/agents/runner.py` / `proposals.py` / `scope.py` |
| 多库 | `docs/RESUME-DATABASES.md` + `apps/hr/models/recruitment.py:259` + `apps/hr/services/resume_search.py:103` |
| 部署 | `docs/DEPLOYMENT.md` + `docs/DEPLOYMENT-VERIFY-2026-08-17.md` + `installer/production_landing.sh` |
| 注销 | `specs/2026-08-15-hr-tenant-offboarding-design.md` + `apps/hr/services/offboarding.py` + `apps/system_manage/services/workspace_offboarding.py` |
| 前端 | `docs/HR-FRONTEND-GUIDE.md` + `ui/src/router/modules/hr.ts` + `ui/src/views/hr/agents/index.vue` |
| 评测 | `docs/SCREENING-EVAL-2026-08-18.md` + `installer/resume_ingest_n.py` / `resume_search_eval.py` |

---

## 6. 风险提示

- **最大风险是「带脏工作区发布」**：54 文件未提交 + 迁移未入 HEAD，任何生产发布前必须先冻结基线并全量回归
- **次大风险是「真实 PII 未经全链路脱敏复核就上线」**：PRD §7 明确为上线阻塞项，`DATASET/train.json` 的 300 份语料虽已做 30 例 PII 扫描，但生产链路（S3/key/日志/审计/索引）需重做
- **模型风险**：单一 `flash-lite` 在正样本 64-65% 召回已见天花板，阈值 80/60 未经强模型对比即冻结会固化误拒
- **运维风险**：三容器单机 + 单 worker + 文件探针的组合在 50 并发下未压测，`MAXKB_*` 环境变量缺少启动期必填校验，静默回退可能掩盖配置错误

---

*生成于 2026-08-20，基于 `HANDOFF.md` 154 行 + `README-hr.md` + `PRD/PRD-AGENT-RAG/ATS-V2/RAG-V2/RESUME-DATABASES/DEPLOYMENT` 全量阅读与 `apps/hr` 代码抽样。后续应在冻结干净 HEAD 后用 `uv run python manage.py test ... --keepdb` + `ruff` + `vue-tsc` + `vite build` 的全绿报告替换本节基线声明。*
