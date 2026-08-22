# 全项目代码审查报告 C 轮：HR 模块纵深审查（2026-08-22）

> 配套文件：`CODE-REVIEW-2026-08-22.md`（A 轮，内核面全仓扫描）、`CODE-REVIEW-2026-08-22b.md`（B 轮，核心链路人工复核）。
> 本轮为**独立第三意见**，聚焦 `apps/hr`（含 agents 前后端与数据层）的六路并行专项审查：安全与多租户 / ATS 业务逻辑 / Agent 运行时 / 简历 RAG 链路 / 模型与迁移 / 前端。
> 基线：commit `54c8cd2`（v2 分支，工作树干净）。全部 P1 结论均经第二轮人工读码或运行时实测复核；只读审查，未修改业务代码。

## 0. 结论速览

| 级别 | 数量 | 与 A/B 轮的关系 |
|---|---|---|
| P0 | 0 | 未发现跨租户对象读写级问题 |
| P1 | 6 | 3 项与 A/B 重合（city/CSV 导入/similar_jobs，本轮独立复现）；**3 项为本轮新增**（hr_members 泄露、edit_job 关闭旁路、trgm 索引缺失） |
| P2 | ~16 | 绝大多数为本轮新增 |
| P3 | ~15 | 卫生/加固类 |

静态佐证：全量后端 **528 tests OK**（--keepdb）、`ruff check apps/hr` 干净、`makemigrations --check` 无漂移。但注意 B 轮的正确提醒：**该测试基线含约 30 处被掏空的 "0030 stub"，对删列残留类回归无保护力**——本轮 4 个功能损坏 P1 正是被这些桩掩盖的。

---

## 1. P1（全部经二次核实）

### C-P1-1【安全】hr_members 回退分支是死代码，实际返回全平台用户目录
- `apps/hr/serializers/access.py:29-31` ← `apps/users/serializers/user.py:593-629`
- 已验证链条：本 fork 从不定义 `settings.MODEL_HANDLES`，`DatabaseModelManage.init()` 只注册返回空 dict 的 DefaultHandle（`default_base_model_handle.py:13`）→ `get_model("workspace_user_role_mapping")` 恒为 None → 内核 `get_user_members` **恒走 fallback 返回全平台非管理员用户**（非空）→ access.py 里「防跨租户枚举」的本工作区回退（32-52 行）永不执行。`tests.py:1070` 只 patch 了「返回 []」的假场景所以测试全绿。
- 影响：① 任意 HR VIEWER 经 `GET /hr/members` 枚举全实例用户 id/nick_name；② `set_access` 与两处 `_interviewer_user_id`（`application_service.py:165-170` 等）的成员校验整体失效，可把任意平台用户指派为面试官，使其经 `/hr/interviews/mine` 接触候选人姓名并提交反馈。
- 修复：内核成员缺失时让 `get_user_members` 返回空或显式报错，由 `hr_members` 用「HrAccess ∪ 已指派 owner/interviewer」真实兜底（交集语义）；补一条不 patch 的端到端回归。

### C-P1-2【功能】edit_job 可直改 CLOSED，绕过两阶段关闭全部级联
- `apps/hr/serializers/recruitment.py:732-741`（对照 `application_service.py:455-514`）
- ADMIN 对 OPEN 职位 `PUT {"status":"CLOSED","close_reason":...}`：不走 close-preview/STRICT/BULK，ACTIVE 申请不关闭、DRAFT/SENT Offer 不撤回、无 ApplicationEvent；此后 send/accept offer 照常可走 → 「已关职位上发出并接受 Offer → HIRED」脏账。同一迁移两个入口两种语义。
- 修复：edit_job 拒绝迁往 CLOSED 并指向 `/jobs/{id}/close`，或在 status 分支内复用 STRICT/BULK 级联。

### C-P1-3【性能宣称失实】raw_text 承诺的 pg_trgm GIN 索引不存在
- 全仓 grep `pg_trgm|GinIndex|gin_trgm_ops|TrigramExtension` **零匹配**；0029 仅 AddField。HANDOFF.md:134 与 PRODUCTION-GAP-ANALYSIS 的「0029 + pg_trgm GIN」与现实不符。
- 影响：`resume_search.py:190,394`、`recruitment.py:403,1099` 的 `raw_text__icontains` 及共享 Paragraph 表 `content__icontains`（185,399）全部顺序扫描，简历上千后检索线性劣化。
- 修复：新迁移 `CREATE EXTENSION pg_trgm` + 表达式索引 `GIN (UPPER(col) gin_trgm_ops)`（icontains 编译为 UPPER LIKE，普通 trgm 索引用不上）；文档对账。

### C-P1-4~6【0030 残留】（承 A/B 轮，本轮独立复现并补齐根因链）
1. **city 过滤必 500**：`application_service.py:582-584` 引用已删列，`application_views.py:68` 直传 query_params；已实测 FieldError。守卫测试 `tests.py:5828` 被掏空成 `assertTrue(True)`。
2. **CSV 导入必然崩溃**：`import_service.py:60-92` 向 `Candidate.objects.create()` 传 13 个已删字段并调用 5 个已不存在的 helper；仅捕 AppApiException → TypeError 500；模板仍在下发旧表头。
3. **similar_jobs 击穿 JD/Copilot**：`similar_jobs.py:21,24` 已运行时验证 Candidate 无 `years_experience` 属性；任一相似职位有 ≥1 条 HIRED 申请即 AttributeError → 整个 run FAILED。对应单测同为 stub。

---

## 2. P2（本轮新增为主）

| # | 问题 | 位置 |
|---|---|---|
| 1 | 入职交接 Webhook SSRF：URL 仅限长度≤512，`urlopen` 直连可打内网/云元数据（跟随重定向），payload 含明文手机/邮箱，accept/retry 自动触发且 retry 无上限 | `offer.py:439-455,564-581` |
| 2 | 模型引用不校验 workspace 归属（slim 内核授权模型机制缺位致条件短路放行他租户模型，消耗其凭证） | `models_provider/tools.py:112-121` |
| 3 | pydantic 版 Screening 以模块级全局 set 存证据白名单，并发 run 互相污染、防编造校验失效（legacy 版参数传递是对的，迁移引入回归） | `agents/runner_pydantic.py:69,248` |
| 4 | Copilot/Sourcing 及全部 pydantic 变体无证据 paragraph_id 服务端校验，「引用忠实度 ≥95%」验收只在 Screening 成立；Sourcing 还回填未投影字段进 payload | `copilot_runner.py:84-91`、`sourcing_runner.py:94-100` |
| 5 | 并发/速率护栏 check-then-write 竞态可击穿上限；手动 API 在请求线程内同步跑 LLM（含退避 sleep 占住 worker 数十秒）；SKIPPED 计入速率分母自我放大 | `agents/base.py:20-35`、`views/agent_views.py:90-98` |
| 6 | propose() 同目标一刀切过期：零风险 COMMUNICATION_DRAFT 会挤掉同申请待决的 ADVANCE/DECLINE 决策提案（收件箱丢待办）；采纳率把 EXPIRED 计入 decided 分母系统性稀释标定指标；分数带硬编码 60/80 与 HOLD=48 漂移 | `agents/proposals.py:35-40`、`services/agent_stats.py:70-74,15-23` |
| 7 | workbench retry_run 固定走 legacy runner，绕过 USE_PYDANTIC_AI 开关：同一失败正常路径与重试路径行为语义不同 | `services/agent_workbench.py:13-17,285-333` |
| 8 | update_interview 可任意改写他人面试状态/反馈且零审计（绕过「仅本人提交」约束）；submit_feedback 无状态前置与截止强制，已定结论可翻转刷新 submitted_at | `recruitment.py:1175-1198,1297-1313` |
| 9 | 文档要求「OFFER 阶段拒绝/撤回前先处理 SENT Offer」代码缺失（SENT 滞留在途）；「同申请至多一条 DRAFT/SENT Offer」无 DB 条件唯一兜底，create/send 双查后写竞态（承 A #13 并发窗口） | `application_service.py:338-385`、`offer.py:154-176,244-247` |
| 10 | update_offer 允许修改已 APPROVED 未 SENT 的薪金/备注而不重置 approval_status —— 审批后可换内容再发送 | `offer.py:192-205` |
| 11 | Screening 信号在事务内 `.delay()` 缺 on_commit：worker 先于 COMMIT 拾取则初筛触发静默丢失（无 FAILED 账本可追溯）；外层回滚产生幻影任务 | `signals.py:15-35`、`runner.py:467-471` |
| 12 | ResumeFile.save() 内联总库引导：查后写并发不安全（撞 `workspace_name_uniq` 上传 500）、与 serializer 层重复实现、每次 save 重复执行引导查询（承 A/B 边角项，本轮确认双实现漂移） | `models/recruitment.py:273-299` |
| 13 | 内核 Document.delete() 无 `meta.hr_protected` 校验（Knowledge 层有守卫、Document 层没有）：常规文档接口可删简历语义索引的单 Document，ResumeFile.document_id 悬空、该简历语义+段落腿静默失效仅剩 raw_text 腿 | `knowledge/serializers/document.py:820-837` |
| 14 | `_terminal` 幂等键对顺序重试失效（status 检查先于幂等事件查找，重试得 400 而非幂等结果；move_stage 顺序相反是对的） | `application_service.py:346-355` vs `300-309` |
| 15 | 硬条件检索静默退役：`hard_slots=False` 写死（预筛整段死代码），但 `meta["slots"]` 仍解析上报年限/学历/城市槽位误导调用方；违反 RAG-V2-DESIGN G1「精确条件 100% SQL 保证」，`_candidate_matches_hard_slots` 恒真桩使 wrapper 过滤为 no-op | `resume_search.py:106-108,650-652,683` |
| 16 | 前端：`/hr/jobs/new` 路由放行 OPERATOR 但建职位/技能抽取后端均 ADMIN，OPERATOR 手输 URL 白填整表单必吃 403；axios 拦截器不处理 5xx/网络错误叠加页面普遍 `.catch(()=>{})`，服务端故障用户零反馈 | `ui/src/router/modules/hr.ts:75`、`ui/src/request/index.ts:63-89` |

数据合规类补充：
- 0030 迁移无任何数据归档即物理删除含知情同意（consent_status/version/collected_at）在内的 13 列，合规审计证据链断裂（reverse 只能回加空列）。建议导出留痕签核（`migrations/0030`）。

## 3. P3（择要）

- **死代码/漂移**：`split_resume_with_skills` 的 skills 解析链在 prompt 撤回后恒空；`extract_skills_llm` 成孤儿；`parse_resume_text` 返回残键；前端 Sourcing skills 标签块/constants.ts 合规常量/sourcing_runner 字段透传三处跨端死链路；`_parse_skills` 同源残留。
- **加固**：ILIKE `%`/`_` 未转义（无注入，放大匹配面）；技能段落兜底查询未先限定工作区文档集（承 B P2-1）；VIEWER 可用联系方式子串做存在性探测 oracle；上传临时文件异常路径残留 /tmp（PII 明文）；Offer 附件无类型白名单；未处理异常原文直返客户端、resume.error_message 对 VIEWER 可见；search_to_llm 简历 chunk 缺防御性掩码（入库侧有双保险，纵深不一致）。
- **观测/一致性**：token 记账只记最后一次尝试、FAILED 运行零记录；新版 runner provider 异常不重试（五 Agent 重试语义不一）；sourcing 工具轨迹计时器错位恒≈0ms；edit_job 审计无 before/after 且 headcount 可低于在招数；面试时间字段零格式校验（非法值 500）。
- **杂项**：`router.push('/404 ')` 尾随空格；前端 workspace_id 回退 `'default'` 必败请求产生审计噪音；0025 注释断言 DEFERRABLE 与真实 schema 不符、replay 映射取 first() 可能错配 reapply 历史；flow log EXTRACT/SPLIT 节点明文存简历全文需留存策略（A #11 的 TTL 漏删同源）。

## 4. 通过项（本轮抽查验证）

- 83 条 HR 路由认证装饰器全覆盖；IDOR 取数路径一致带 workspace 过滤、跨租户统一 404 泛化；写接口「视图装饰器 + 服务层 require_operator/manage」双层校验。
- VIEWER 手机/邮箱脱敏在服务端做（搜索结果/提案输出/事件输出一致）；scope.py 库范围校验严密（ACTIVE+归属+≤50+UUID）且检索侧独立二次校验；知识库白名单服务端强制并排除 hr_protected。
- LLM 失败→run=FAILED 业务零影响成立（propose 仅成功路径调用）；celery-once 防重可靠；APPLY 自动触发双闸门控正确。
- ATS 核心状态机：ACTIVE 部分唯一约束、select_for_update、幂等事件、HIRED 仅经 accept_offer 同事务触发、round_no 服务端生成+DB 唯一。
- 前端 HR 页面零 v-html（AI 文本全插值）、权限三层防护（按钮隐藏/路由 meta/后端装饰器）、构建 base 配置与生产路径修复一致。

## 5. 修复优先级建议（C 轮视角，与 A/B 合并看）

1. **立即**：C-P1-1 hr_members（一行交集语义即可消除泄露面）；C-P1-2 edit_job CLOSED 收口；A/B 已确认的 0030 清剿三件套（city/CSV/similar_jobs）+ 恢复 stub 测试。
2. **本周**：webhook URL 校验（https+私网段拒绝+异步投递）；C-P1-3 trgm 表达式索引迁移；pydantic 白名单改 contextvars/deps；Offer 条件唯一约束 + 审批后禁改；信号 on_commit；Document 层 hr_protected 守卫。
3. **随后**：证据校验统一到所有 runner；护栏原子化（Redis 锁）+ 手动触发异步化；采纳率口径修正；retry_run 路由统一；hard_slots 退役的 meta 如实标注或按 raw_text 重建硬条件。
4. **对账**：HANDOFF/RAG-V2-DESIGN 中「预筛 applied」「pg_trgm GIN」「recall@5=0.92 前提变化」等失实表述随修复同步修订。
