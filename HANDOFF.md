# MaxKB 人事招聘工作台 · 项目交接与开发提示词

> 本文件是给新开发平台/AI 助手的项目状态提示词。请先完整阅读本文件，再按需阅读 docs/PRD.md、docs/superpowers/ 下的规格与验收文档。

## 0. 一句话定位

在精简版 MaxKB v2（Django + DRF + Vue3）内核内嵌的多租户人事招聘工作台（ATS），业务全部在 `apps/hr`，已完成基础闭环、简历解析/检索、面试 Offer 状态机、AI 搜人、异步化、简历合并查重，以及「A 阶段生产基础补齐」（流程模型、访问控制与审计、数据生命周期）。

## 1. 技术栈与关键约束

| 项 | 内容 |
|---|---|
| 后端 | Python 3.11 / Django 5.2 / DRF / PostgreSQL 16(pgvector) / Redis / Celery（celery-once 防重） |
| 前端 | Vue 3 / Vite / Element Plus（ui/ 目录，admin 与 chat 两个 SPA） |
| 依赖 | uv（`uv sync --locked`），`uv.lock` 已入库 |
| 数据库/缓存 | docker：`maxkb-slim-pg`（postgres/maxkb-test）、`maxkb-slim-redis`（127.0.0.1:6379） |
| 包管理 | 后端 `uv`；前端 `pnpm`（ui/） |
| 代码风格 | ruff（line-length 120）、vue-tsc；提交用中文 Conventional Commits |

### 1.1 运行测试（关键！本机无 config.yml）

```bash
export MAXKB_CONFIG_TYPE=ENV \
  MAXKB_DB_NAME=maxkb MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
  MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
  MAXKB_DB_ENGINE=django.db.backends.postgresql MAXKB_DB_MAX_OVERFLOW=10 \
  MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_PASSWORD= \
  MAXKB_REDIS_DB=0 MAXKB_REDIS_MAX_CONNECTIONS=10

uv run python apps/manage.py test hr.tests --keepdb            # HR 全量
uv run python apps/manage.py test hr.tests application.tests knowledge.tests models_provider.tests ops.tests --keepdb  # 四 app + ops 全量
uv run python apps/manage.py makemigrations --check --dry-run  # 迁移漂移检查
uv run python apps/manage.py migrate --check                   # 未应用迁移检查
uv run ruff check apps/hr/
```

注意：`--keepdb` 首次跑可能因测试库缺最新迁移报瞬态错误，复跑即通过；不要据此误判代码缺陷。若测试报「source database maxkb is being accessed by other users」，说明测试库需要重建：`DROP DATABASE test_maxkb;` 后重跑（见第 5.1 节与提交 `fe42c65`）。

### 1.2 前端验证

```bash
cd ui
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build >/dev/null 2>&1 && echo ADMIN_OK
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat >/dev/null 2>&1 && echo CHAT_OK
```

## 2. 权威文档（按优先级）

| 文档 | 用途 |
|---|---|
| `docs/PRD.md` | 产品基线：定位、业务对象与状态机、权限、上线门槛、交付状态（第 9 节）、路线 |
| `docs/superpowers/specs/2026-08-14-hr-process-model-design.md` | A2 流程模型（职位状态/关联字段/状态迁移矩阵） |
| `docs/superpowers/specs/2026-08-14-hr-access-audit-design.md` | A3 访问控制与审计 |
| `docs/superpowers/specs/2026-08-14-hr-lifecycle-design.md` | A4 数据生命周期（删除匿名化/TTL/导出） |
| `docs/superpowers/audits/2026-08-14-hr-production-baseline.md` | A 阶段验收基线 + 部署验证项清单 |
| `README-hr.md` | 各期验收记录（一期到 A 阶段，含测试数演进） |
| `docs/superpowers/specs/2026-08-13-*.md` | 二至七期规格（简历/搜索匹配/AI/异步/合并） |

## 3. 已完成（当前测试基线：四 app + ops 383/383 PASS，HR 349）

### 3.1 PRD 七期（基础能力）

| 期 | 内容 | 验收 |
|---|---|---|
| 一 | 候选人/职位/指派基础闭环、工作区隔离 | 23 |
| 二 | 简历上传、docx/txt 规则解析、内容哈希去重、检索 | 31 |
| 三 | 组合搜索（多技能 AND/学历/年限区间）、职位匹配建议 | 39 |
| 四 | 状态机扩展（面试中/Offer/已入职）、面试轮次与反馈 | 47 |
| 五 | 工作区 LLM 配置、自然语言搜人、职位技能抽取 | 76 |
| 六 | Celery 异步简历解析（QueueOnce）、批量状态查询 | 86 |
| 七 | 简历下载/原文查看、手机号/邮箱查重、候选人合并 | 107 |

### 3.2 A 阶段（生产基础补齐，2026-08-14，14 个提交 b5c518d..520d288）

- **A1 流程口径**：归档拦截与 HC 统计覆盖全部进行中状态；候选人详情入口
- **A2 流程模型**：职位 `DRAFT/ON_HOLD/CLOSED`（close_reason）+owner；关联 `relation_type/channel/applied_at/owner_id/termination_reason/is_reapply` + `WITHDRAWN` 状态；服务端强制状态迁移矩阵（规格中有迁移表）；关闭职位批量收尾（PUT /jobs/{id}/close）；重新投递自动标记；误拒绝仅管理员恢复（REJECTED→PENDING_SCREEN）
- **A3 访问控制与审计**：`HrAccess`（VIEWER/OPERATOR/ADMIN 显式授权）、`hr_access_required`/`hr_admin_required` 装饰器、VIEWER 联系方式脱敏、`HrAuditLog` 操作审计（查看/创建/流转/简历/合并/导出/授权/越权拒绝）、人事成员与审计日志页面
- **A4 数据生命周期**：候选人合规元数据（source_type/source_detail/collected_at/consent_status/consent_version/contact_preference）；删除匿名化（DELETED 终态、PII 清空、简历联动删除，进行中/HIRED 拒绝）；未关联简历 30 天 TTL 每日 Celery 任务（`cleanup_orphan_resumes`，beat 注册在 task/resume.py 的 worker_ready 信号幂等创建（勿放回 apps.py ready，见 fe42c65））；受控白名单 CSV 导出（不含联系方式、公式注入转义）
- **A5 验收**：227/227 PASS；部署验证项已列出（见第 5 节）

### 3.3 关键实现模式（新功能必须遵循）

- **工作区隔离**：服务层每类资源按 `workspace_id` 过滤；跨工作区一律 404（不泄露存在性）；`GET /candidates/{id}` 对 DELETED 行限 ADMIN
- **权限**：HR 视图用 `@hr_access_required` / `@hr_admin_required`（views/permissions.py）；服务层 `_require_manage()` 等价 ADMIN；未授权写 ACCESS_DENIED 审计
- **状态机**：服务端是唯一权威（`_ALLOWED_TRANSITIONS` 矩阵）；终态必填终止原因；非法流转 400 含当前/目标状态
- **审计**：`write_audit_log(workspace_id, user_id, action, object_type, object_id, detail=...)`（services/audit.py）；敏感操作必须埋点
- **脱敏**：VIEWER 角色 phone `138****5678`、email `ab***@example.com`（_masked_phone/_masked_email）
- **并发**：合并/关闭职位/建关联用 `select_for_update` 固定行锁顺序（primary 先于 secondary）；锁内重查校验避免 TOCTOU
- **路由顺序教训**：`check-duplicate` 等静态段必须放在 `<str:xxx>` 动态段之前，否则被吞
- **表单输入**：枚举字段服务端校验 400；UUID 参数用 `_owner_id` 类校验器，避免 500

## 4. 审查发现并已修复的问题（避免重蹈）

- merge 冲突检查 TOCTOU → 事务 + 行锁
- saveCandidate 双提防护 promise 链未贯通 → `.then` 全分支 return，finally 覆盖保存完成
- owner_id 非法 UUID → 500（应 400）
- edit_job 绕过关闭专用语义（CLOSED 不带原因、CLOSED→OPEN）
- CSV 公式注入（= + - @ 前缀转义）
- DELETED 终态可被 edit/merge/archive 复活 → 三处 400 拒绝

## 5. 下一步（按优先级）

### 5.1 部署环境验证（A 阶段关闭前提，处理真实 PII 前必须完成）

- Celery worker+beat 真实调度：**heartbeat.py 硬编码 `/opt/maxkb-app/tmp`** → 已修复（2026-08-15）：探针目录改为 `MAXKB_WORKER_TMP` 环境变量覆盖、默认值不变（向后兼容）；新增 `apps/ops/tests.py` 4 用例，全量 231/231。**已真实验证（2026-08-15）**：本机 `MAXKB_WORKER_TMP=/tmp/maxkb-worker-tmp` 启动 worker 成功，`worker_ready/worker_heartbeat` 探针文件生成，beat 任务 `hr-cleanup-orphan-resumes`（每日 03:00）注册成功；31 天前孤儿简历经真实 worker 执行清理（物理文件删除 + RESUME_DELETE 审计）。**web 全链路冒烟（2026-08-15）**：真实 HTTP 跑通 登录→职位→候选人→指派→OFFER→面试→Offer 审批/发送/接受→交接 SUCCESS→CSV 导入→归档/恢复→审计（15/15 PASS）。TTL 清理 beat 任务（`hr-cleanup-orphan-resumes`）在 `apps/hr/task/resume.py` 的 `worker_ready` 信号中注册（勿改回 apps.py ready——那会在应用加载时访问数据库，导致测试库模板克隆被连接占用而失败，见提交 `fe42c65`）
- 对象存储私有化 → **已实现并本机验证（2026-08-15）**：`hr/services/storage.py` 存储抽象（`MAXKB_STORAGE_BACKEND=local|s3`，MinIO/S3 兼容，minio SDK），简历/Offer 附件/清理任务全走 StorageBackend；本地后端兼容存量绝对路径。MinIO 集成验证：上传/下载/删除往返 + 无凭据访问 403（私有读）。生产按 `MAXKB_S3_*` 配置真实对象存储即可
- TLS、数据库/备份静态加密、密钥管理 → **本机模拟验证（2026-08-15）**：自签证书 + gunicorn `--certfile/--keyfile` HTTPS 生效（明文 HTTP 拒绝）；备份加密闭环（`installer/backup.sh`：pg_dump+gzip+AES-256+轮转，解密恢复验证数据完整）；密钥只走环境变量、不出现在日志/请求参数（`main.py` TMPDIR/HF_HOME 已改 setdefault 可覆盖）。生产部署：真实 CA/证书链、PG sslmode=require、.env 权限 600 与密钥轮换
- 日志/监控脱敏人工检查 → **已完成（2026-08-15）**：`apps/hr` 无任何 logger/print；异常处理器只记录 `str(exc)+traceback`（不含请求体/局部变量）；简历文本仅用于解析、失败写 DB error_message 不落日志；附件/简历文件名带 UUID 前缀。**部署侧验证**：真实 PII（手机/邮箱/密码/DB 密码）跑全链路后 grep 落盘日志（maxkb.log/drf_exception/unexpected_exception）PII 命中 0、无 500 异常。剩余：syslog handler 与监控标签的部署侧复核
- 备份自然过期、租户注销与数据返还/删除流程 → 备份轮转已实现（backup.sh 默认保留 7 份自然过期，本机验证）；租户注销/数据返还流程设计见 `docs/superpowers/specs/2026-08-15-hr-tenant-offboarding-design.md`（企业部署协议层，未编码，部署时按设计落地）

### 5.2 B 阶段：招聘协作与 Offer 交接（PRD 9.2）

| 项 | 内容 |
|---|---|
| 完整面试协作 | **v1 已交付（2026-08-15）**：面试官用户化（interviewer_user_id）、最小可见（我的面试仅本人 + 无 PII 字段）、反馈截止（feedback_deadline + is_overdue）、反馈可追溯（feedback_submitted_at + INTERVIEW_FEEDBACK 审计）、前端「我的面试」页面；见 docs/superpowers/specs/2026-08-15-hr-interview-collaboration-design.md。剩余：自动提醒、面试官可见简历等（未排期） |
| Offer 工件 | **已交付（2026-08-15）**：独立实体（hr_offer）+ 版本自增 + 审批（approval_status/approver）+ 金额/币种（Decimal）+ 状态机 DRAFT→SENT→ACCEPTED/REJECTED/WITHDRAWN + 接受自动流转 HIRED + 附件上传/下载权限（VIEWER 不可下载）+ 5 个 OFFER_* 审计动作；见 docs/superpowers/specs/2026-08-15-hr-offer-design.md |
| 入职交接 | **已交付（2026-08-15）**：OnboardingHandoff 按指派唯一（幂等）+ 固定清单 payload（含联系方式）+ CHECKLIST/WEBHOOK 目标（urllib 同步投递，零新依赖）+ 失败可重试（仅 FAILED）+ HANDOFF 审计 + 交接页面与配置接口；见 docs/superpowers/specs/2026-08-15-hr-onboarding-handoff-design.md。异步化投递（Celery）与真实 HRIS 适配器未排期 |
| 批量导入 | **已交付（2026-08-15）**：CSV（UTF-8/BOM）逐行校验导入（ADMIN），失败行跳过并报原因、文件内/库内疑似重复标注（仍创建）、汇总+明细报告、模板下载、IMPORT 审计 + 逐条 CREATE 审计；≤200 行/≤2MB；见 docs/superpowers/specs/2026-08-15-hr-csv-import-design.md。**至此 B 阶段（面试协作/Offer/入职交接/批量导入）全部完成** |

### 5.3 C 阶段：语义检索与智能优化

**试点进展（2026-08-15，外部模型接入已完成）**：OpenAI 兼容 Provider 注册 LLM `sensenova-6.8-flash-lite`（SenseNova）、Embedding `BAAI/bge-large-zh-v1.5` + Rerank `BAAI/bge-reranker-v2-m3`（SiliconFlow）；RERANKER 模型类型补齐（model/rerank.py + credential/rerank.py，top_n 默认 3）。真实模型端到端验证（`installer/real_model_smoke.py`，`RUN_REAL_MODEL=1` 门控 + 渐进档位 1|2|3）：S1（5 份简历）17/17、S2（30 份）向量化 30/30 + 问答引用；实体查询 recall@5=3/8 低于结构化基线（佐证实体检索走结构化）、自然语言查询召回合理。密钥走环境变量（`.env.example` 有占位）。规格/审计：`docs/superpowers/specs/2026-08-15-external-model-pilot-design.md`、`docs/superpowers/audits/2026-08-15-external-model-pilot.md`。

**设计定稿（2026-08-15）**：端到端综合方案 docs/superpowers/specs/2026-08-15-end-to-end-pipeline-combined-design.md（**唯一权威**，§6 含切片协议 v4：LLM 边界标注 + 条目级 + 禁止改写 + PII 过滤）；实施计划 docs/superpowers/plans/2026-08-15-c-stage-resume-rag.md（**执行依据**）；GitHub 调研 docs/superpowers/audits/2026-08-15-chunking-landscape.md；真实数据审查 docs/superpowers/audits/2026-08-15-design-reality-check.md（输入按 PRD 锁定 docx/txt；docx 表格排版与 OCR 分号流已支持——见下方实现进展；数据集合成为压力测试语料）。

**C 阶段实现进展（2026-08-15）**：
- ✅ 阶段 1（切片器）：sanitize_resume_text() + ResumeSplitter（LLM 行号边界标注 + L2 校验 + L3 规则/smart 降级 + PII 掩码），单测 11 例（19637e8 初版 9 例 + e1c16e3 超长单行/超长段降级 2 例）；真实模型冒烟 10/10 保真、0 异常；
- ✅ 阶段 2（打通入库）：ResumeFile.document_id（迁移 0013）+ hr/services/resume_index.py（简历知识库幂等创建/入库/删除/启停用）+ parse_resume_task 自动索引（失败不阻塞建档）+ 生命周期同步（删除/合并清文档、归档/恢复切 is_active）+ 状态接口暴露 document_id；单测 5 例；端到端冒烟通过（上传 3 份 → LLM 切片 → 向量化 SUCCESS → 检索命中"幕墙系统设计" 0.665）（提交 ce8f065/1486cac）；
- ✅ 数据流转日志：ResumeFlowLog（迁移 0014/0015）+ 流转日志 API GET /workspace/{ws}/hr/resumes/{id}/flow-logs + UPLOAD/EXTRACT/SANITIZE/SPLIT/DOCUMENT/LIFECYCLE 六节点持久化；SPLIT 节点 detail 含每个 chunk 完整内容（title/content/length/pii），EXTRACT/SANITIZE 保留全文，失败节点记 status=FAILED+error_message；**权限：EXTRACT/SANITIZE 含未脱敏全文，flow-logs API 要求 OPERATOR+（VIEWER 403，防绕过 VIEWER 脱敏读取 PII）**；单测 4 例（提交 b70f9d2/5043340 + PII 权限修复）；
- ✅ docx 表格排版简历提取：extract_text_from_docx 补表格单元格遍历（合并单元格按 _tc 对象去重，修复 id() 复用陷阱）；数据集真实 docx（表格排版、paragraphs 为空）全流程验证 8 段 → 检索命中 0.758（提交 a72b2b9）；
- ✅ 数据集 30 份切片压力测试 + 两处生产修复（提交 af4c52a）：(1) **SenseNova 6.8 模型行为变化**——默认输出 reasoning 推理流耗尽 max_tokens 致 content 为空、LLM 路径 0% 命中；OpenAI 兼容适配器对 sensenova 透传 model_kwargs={"thinking": {"type": "disabled"}}，实测 106 tokens 完成切片、LLM 路径恢复 29/30；(2) **OCR 分号流**（PaddleOCR 单行"简历；；；姓名；…"输出）使行号边界协议失效——sanitize_resume_text 增加分号流自动转行（分号 ≥5 且基本无换行时触发，正常多行文本不受影响）。测试结果：30/30 成功、29/30 LLM 路径、30/30 内容无改写（保真度量=非空白序列一致）、PII 26/30 掩码（4 份样本本身无 PII）、全部 ≤500 字、耗时 95s。新脚本 installer/resume_splitter_dataset30.py（可复跑，报告 installer/dataset30_report.json）；
- ✅ 阶段 3.1（检索服务，2026-08-16）：HR 简历语义检索服务（一次 embed → dense+sparse 双路独立召回 → Python RRF(k=60) 融合 → bge-reranker-v2-m3 精排 → Small-to-Big 简历聚合；模式 B Skill-AND 技能复合：LLM 有序技能分解 → 按序逐技能双路召回 → 命中向量字典序 → 顺位放宽 → rerank 精排（skill_ordered_reranked，2026-08-16 补齐设计步骤 6））；POST /workspace/{ws}/hr/resumes/search（hr_access_required，VIEWER 脱敏）；HrConfig.rerank_model_id + SEARCH 审计（查询原文不入库）；单测 13 例（提交 f1cd4ae + 08430c1）。实施中修复：sparse 长查询 AND 漏召回（jieba 截断前 4 词）、sparse 阈值误过滤（内部阈值 0.01）、rerank index 映射错位、rerank 排序被 rrf 聚合覆盖（_para_score 优先 rerank 分）、模式 B 固定命中阈值无区分度（相对阈值 max(0.2, top×0.75)）；
- ✅ 阶段 3.3（量化对比，2026-08-16）：31 份简历语料 + 12 锚点查询 × 5 模式——**RRF+rerank recall@5=0.92 / recall@3=0.83 / Top-1=0.75 / MRR=0.785**，优于 dense-only（0.75/0.513）、RRF（0.75/0.579）、Skill-AND（0.75/0.604），**结构化基线 0.00**（语料 skills 字段为空，正文语义检索价值凸显）；报告落盘 audits/2026-08-15-c-stage-rerank-eval.md。**C 阶段完成定义达成（PRD §9.2）**；
- ✅ 阶段 3 收尾（2026-08-16，提交 08430c1）：模式 B 接入 rerank + 文档同步（README-hr/plans 阶段 3 已完成）+ **HTTP 端到端验收**（真实 web：登录 → 检索 API 模式 A/B 均 200，空 query/非法 mode 返回 {code:400} 业务码，无 token 401，SEARCH 审计落库且查询原文不入库）。全量 355/355；
- ⏳ 可选增强（3.4，按评测收益决策）：路由分级 / 画像重排 / RAG Fusion / title 摘要 / docx 变体集，均未触发（评测显示 rerank 已足够）。
- ✅ **第二轮独立审查修复（2026-08-16，7 项 + 10 例回归，全量 367/367）**：
  - **简历删除/TTL 清理联动语义索引**：delete_resume/cleanup_orphan_resumes 调 delete_resume_index（幂等）；并修复 _delete_document 从不删 Paragraph 的深层缺陷（内核模型 DO_NOTHING 无级联，候选人删除路径同样段落残留，此前孤儿段落会继续被检索命中）；
  - **流转日志 PII 级联清理**：delete_resume/delete_candidate 清理 ResumeFlowLog（EXTRACT/SANITIZE 含未脱敏全文，删除后不留存；HrAuditLog 操作审计保留）；
  - **检索参数与异常加固**：recall_k clamp [5,60]、similarity clamp [0,2]（负数 recall_k 曾触发 PG LIMIT 报错 500）；embedding 模型缺失/embed_query 失败转业务异常（曾裸 AttributeError 500）；
  - **模式 B 结构化路补齐（设计 §2 步骤2）**：Candidate.skills 精确命中与语义路命中向量 OR 合并，仅结构化命中的简历按字典序补位输出；meta 新增 recall.structured_hits；
  - **入库前 PII 二次扫描**：scan_residual_pii（全空格分隔手机号/15 位身份证/16-19 位银行卡变体）残留即拒绝入库（设计 §6.8 承诺，不阻塞建档）；
  - **meta 契约与权限小修**：mode=skills 解析失败 meta.mode 如实为 phrase（此前误导）；meta.rerank.model/sparse_failed 补齐；Download/Content 视图改 hr_operator_required（与服务层一致）；title 上限 20 对齐设计；
  - 已知限制记录（设计文档 §9.3）：简历知识库可被系统管理员经内核知识库 API 读取（绕过 HrAccess，P2 待加固）、模型工作区可见性校验在裁剪内核为 no-op（共享 default 模型为当前产品行为）、LLM 切片调用发送未脱敏全文（合规待确认）。
- ✅ **简历 RAG v2 重构（2026-08-16，T1-T7 七任务 + 16 例回归，全量 383/383）**：设计见 specs/2026-08-16-resume-rag-v2-design.md、方案见 plans/2026-08-16-resume-rag-v2-implementation.md（提交 538a8a8..3797bfe）：
  - **T1 PII 掩码前置**：掩码先于任何 LLM 调用（行内替换不改行号，边界协议不受影响）；保真语义更新为「相对掩码后原文」；scan_residual_pii 仍为入库 backstop；
  - **T2 title 入 chunks**：HR 自建 Document/Paragraph（content 保真、chunks 带 "{title}\n" 前缀参与向量化/分词），显式触发向量化——内核零改动；
  - **T3 证据合成**（仅模式 A）：score = max(段分) + λ·log2(1+命中段数)，λ=0.15（可配，置 0 回退旧行为）；meta.aggregation 新增 evidence_lambda/multi_hit_boosted；
  - **T4 查询理解 v1 + 结构化预筛**：规则槽位（年限/学历/城市/语义词）→ Candidate SQL 预筛 → document 集限定召回；纯条件查询走纯结构化检索（杜绝 embed_query("")）；NULL 年限纳入并标记 years_unknown；城市双向归一；姓名快速通道（2-4 字中文 → name__icontains 置顶）；prefilter_empty 明确返回空不误导；
  - **T5 candidate_skill 归一表**：skill_alias.json ~100 条别名 + 幂等回填命令 backfill_candidate_skills；Skill-AND 结构化路 SQL 化（表空回退 JSON 路径）；
  - **T6 Termbase 词条 + 重嵌命令**：seed_resume_termbase（108 词条，幂等，KeywordsSearch 内部已自动生效）+ reindex_resume_knowledge（dry-run 支持；一次重嵌覆盖 T2 存量 + T6 词条；重嵌窗口检索降级 seq scan，低峰执行；真实执行由项目方操作）；
  - **T7 技能预筛**：LLM 解析技能（auto→phrase）AND candidate_skill EXISTS，与向量 Skill-AND 并存。
  - 已知限制同步：phone/email 语义查找因掩码设计性不可行（v1 不做，产品确认点）；查询理解为规则版（LLM 版并入 P3 合并调用）；城市槽子串匹配可能误中（评测暴露后收紧）。

另：人工反馈、更大标注集量化对比、档位 3（200 份）仍后置。docx 格式变体评测集（plans 1.3）并入阶段 3 检索评测。**注意**：冒烟中修复了应用创建/发布链路的 3 个裁剪期 bug（96afbd0），application.tests 现有 10 用例。

**运行要点**：web `python main.py dev`；celery `PATH=.venv/bin:$PATH MAXKB_WORKER_TMP=/tmp/maxkb-worker python main.py dev celery`；冒烟 `RUN_REAL_MODEL=1 REAL_MODEL_STAGE=1 SENSENOVA_API_KEY=... SILICONFLOW_API_KEY=... python installer/real_model_smoke.py`；检索冒烟/评测 `SENSENOVA_API_KEY=... python installer/resume_search_smoke.py`、`python installer/resume_search_eval.py`（语料入库 `python installer/resume_ingest_30.py`，幂等）。冒烟用户 `smoke-admin`（ADMIN 角色，密码 Smoke@123，仅本机）；模型/知识库/应用 API 只认 `default` 工作区（HR 模块才用自定义 workspace + HrAccess）。

## 5.4 已修复的核心层 bug（2026-08-15，冒烟暴露）

- `to_application_knowledge_mapping`/`reset_application_version` 缺 self → 应用创建/发布必 500，已 @staticmethod 修复（96afbd0）
- `list_knowledge` 误标 @staticmethod 且缺 `KnowledgeScope` 导入 → 发布后读取知识列表必崩，已修复（96afbd0）
- SiliconFlow Embedding 不接受 `dimensions` 参数（OpenAI 兼容差异）→ 模型参数表单留空，bge-large-zh-v1.5 固定 1024 维（pgvector 无维度约束）

## 6. 已知限制与口径

- 面试官已支持用户化（interviewer_user_id，UUID 未建外键，项目惯例）；文本字段保留为显示名/临时外部面试官；负责人存 user_id（UUID）未建外键
- 恢复误拒绝记录到 note（`[restore] <原因>`），未建独立字段
- 导出为固定白名单（不含联系方式）；批量导入已交付（ADMIN、CSV、≤200 行、逐行校验+重复标注），简历文件随 CSV 导入与字段映射未做
- TTL 每日调度，清理延迟最多约 24h
- 候选人「更正请求」由编辑+审计承接，无独立审批流
- 未关联简历允许存在（TTL 兜底）；`ResumeFile.candidate` 为 SET_NULL
- 入职交接为同步投递（accept_offer 请求内），目标 webhook 超时 10s；大批量场景需异步化（未排期）
- PRD 明确：`HIRED` 后不得新建职位关联；仅 REJECTED/WITHDRAWN/CLOSED 可重新投递

## 7. 提交流程与账本

- 每期：docs 规格提交 → docs 实现计划提交 → 实现（TDD）→ 全量验收 → 审查 → 修复
- 测试数演进：23→31→39→47→76→86→107（一期至七期，四 app 口径）→141→183→207→215（A 阶段，切 HR 单 app 口径）→227（四 app = HR 215 + 内核 12）→231（+ops 4）→240（+候选恢复 9）→255（+面试协作 15）→287（+Offer/交接 32）→301（+批量导入 14，B 阶段完成，2026-08-15）→336（C 阶段收尾，6c022e4 文档同步基线，HR 302）→342（HR 308 + 内核 34，2026-08-15：切片器超长降级 2 + docx 表格 1 + 流转日志 3）→**355（HR 321 + 内核 34，2026-08-16 实测：四 app + ops 355/355，342 后新增 13 例 = ResumeSearchTests 11 + AiService 配置扩展 2）**→357（HR 323 + 内核 34，742fafe 审查修复 4 处）→**367（HR 333 + 内核 34，2026-08-16 第二轮审查修复后实测：四 app + ops 367/367，357 后新增 10 例 = 删除清理 2 + PII 二次扫描 2 + 结构化路 2 + 参数 clamp 1 + embedding 友好错误 2 + mode 退化 meta 1）**→**383（HR 349 + 内核 34，2026-08-16 v2 重构实测：四 app + ops 383/383，367 后新增 16 例 = T1 掩码前置 1 + T2 title-chunks 1 + T3 证据合成 1 + T4 查询理解/预筛 7 + T5 技能归一 3 + T6 重嵌命令 2 + T7 技能预筛 1）**
- 规格/计划/验收文档路径规范：`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`、`docs/superpowers/plans/`、`docs/superpowers/audits/YYYY-MM-DD-<topic>-baseline.md`
- 提交信息：`feat(人事)/fix(人事)/docs(人事)/test(人事): 中文描述`

## 8. 文档审计结论（2026-08-15，未修复仅记录）

> 打包前对全部文档做了与代码事实的对照审计。以下问题已于 2026-08-15 **全部处理完毕**（§8.1 六项事实错误、§8.2 六项建议修改、§8.3 功能缺口），处理依据为「代码 + A 阶段规格 + 08-14 验收基线」；下方保留原清单备查。

### 8.1 会误导的事实错误（建议优先处理）

| 文档 | 问题 |
|---|---|
| `docs/PRD.md` §9.1「当前实现边界」表 | 停留在 A 阶段前快照：「职位仅 OPEN/CLOSED」「关联无 WITHDRAWN/负责人」「权限复用工作区成员」「无审计」等，全部已被 A2/A3/A4 交付推翻；而 PRD 头部声明「以第 9 节为准」 |
| `docs/PRD.md` §4.1 与 §8 | 「建档至少姓名+一种联系方式」「服务端必须校验联系方式」规则从未实现（代码仅必填 name），未标注为未达成 |
| `docs/PRD.md` §7 审计门槛 | 「请求追踪标识」未实现（HrAuditLog 无 trace 字段），缺口未标注 |
| `docs/superpowers/specs/2026-08-13-hr-resume-async-design.md` §2.7 | 断言「sha256 唯一约束未在模型层实施」——事实错误（迁移 0003 已有 DB 约束，并发重复实为 IntegrityError 未捕获 → 500） |
| `docs/superpowers/specs/2026-08-14-hr-lifecycle-design.md` API 表 | 「编辑候选人 OPERATOR/ADMIN」与代码实际（仅 ADMIN）及 A3 矩阵矛盾 |
| `README.md`、`README_CN.md`、`CLAUDE.md` | 大量宣称已删除能力：工作流、MCP、函数库、多模态、本地模型（CLAUDE.md 约 12 处：`dev local_model` 命令报错、双 settings 描述、flow 引擎、sandbox 运行时、多供应商列表等）；README 宣称「workflows / MCP tool-use」 |

### 8.2 建议修改（可后置）

| 文档 | 问题 |
|---|---|
| `HANDOFF.md` §7 | 测试数演进链口径混用：23→107 为四 app 口径、141→215 为 HR 单 app 口径，未标注切换且漏 99；全量应表述为「四 app 227 = HR 215 + 内核 12」 |
| `README-hr.md` 第 76 行 | 「复用当前工作区认证与管理员权限」已过时（A3 后为 HR 显式授权） |
| `docs/PRD.md` §6 | 「AI 复用工作区管理端权限、显式授权属 A 阶段门槛」已过时（A3 已落地） |
| `docs/superpowers/specs/2026-08-14-hr-process-model-design.md` API 表 | `GET /assignments` 未实现（列表能力由 job/candidate 详情承载） |
| `CONTRIBUTING.md`、`SECURITY.md` | 仍指向上游 GitHub 链接，与本 fork 流程不符 |
| `docs/superpowers/audits/2026-08-14-hr-production-baseline.md` | 「分支 main」应为 v2 |

### 8.3 真实功能缺口（文档宣称但未实现，非文档问题）

| 缺口 | 说明 |
|---|---|
| **候选人恢复（ARCHIVED→ACTIVE）** | **已修复（2026-08-15）**：新增 `PUT /candidates/{id}/restore`（ADMIN，`hr_admin_required` + `_require_manage` 双层校验）、`restore_candidate` 服务方法（DELETED/非 ARCHIVED 拒绝 400）、`RESTORE` 审计（object_type=CANDIDATE）、前端列表/详情恢复按钮；9 个新测试，全量 240/240（见规格 `docs/superpowers/specs/2026-08-15-hr-candidate-restore-design.md`）。RESTORE 审计动作现同时用于指派误拒绝恢复（ASSIGNMENT）与候选人恢复（CANDIDATE） |

### 8.4 历史阶段记录（非错误，可保留）

一期至五期规格中的「状态只覆盖筛选阶段」「不新增审计表」「同步解析」「工作区成员权限」等，是当时正确、被后续阶段明确修订的决策记录；四期取舍「不引入审计表」已被 A3 推翻。判断优先级时以 §2 文档排序为准。
