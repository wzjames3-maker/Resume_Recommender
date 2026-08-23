# MaxKB-HR 项目代码审查总报告（2026-08-22 · 合并版）

> 本文件是当日三轮审查的**去重合并完整版**：
> - A 轮 `CODE-REVIEW-2026-08-22.md`：4 并行代理全仓扫描（内核面：oss/chat/application/common/users/ops）
> - B 轮 `CODE-REVIEW-2026-08-22b.md`：核心链路人工深审 + 运行时验证
> - C 轮 `CODE-REVIEW-2026-08-22c-hr-deep.md`：HR 模块六路纵深审查（安全/状态机/Agent/RAG/数据层/前端）
>
> 标注说明：【✅亲验】= 合并时二次读码或运行复现；【A】【B】【C】= 首发轮次；基线 commit `54c8cd2`。
> 静态佐证：后端全量 528 tests OK（--keepdb）、`ruff check apps/hr` 干净、`makemigrations --check` 无漂移；
> ⚠️ 但该测试基线含约 30 处被掏空的 `# 0030 stub assertTrue(True)`，对「删列残留」类回归**无保护力**。

---

## 0. 执行摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| P0 | 1 | ENV 模式 `MAXKB_DEBUG=false` 实际开启 DEBUG |
| P1 | 12 | 内核密钥/反序列化 3 项；跨租户泄露 2 项；0030 功能断裂 4 项；关闭旁路 1 项；索引失实 1 项；合规 1+ 项 |
| P2 | ~27 | 出站集成（SSRF/模型归属）、Agent 运行时结构性弱点、Offer/Interview 状态一致性、日志与边界配置 |
| P3 | ~20 | 加固/观测/死代码 |

**总体判断**：架构骨架扎实——workspace 隔离纪律、双层权限、PII 掩码管线、「AI 只写 Proposal」红线、ATS 核心状态机约束均经抽查验证为健全；未发现跨租户对象读写级 P0。主要风险集中在四处：① 生产部署安全默认值（P0-1 与密钥族）；② 0030 删列「删列成功、清尾失败」（4 条主流程损坏且被 stub 测试掩盖）；③ 出站集成边界（SSRF 家族、模型租户归属）；④ Agent 双轨 runner 的结构性漂移。

---

## 1. P0

### P0-1 ENV 模式布尔解析缺陷：`MAXKB_DEBUG=false` 实际开启 DEBUG【B 轮实测复现，✅亲验代码链】
- `maxkb/conf.py:52-53,224-248`：load_from_env 原样存字符串，`get_debug()` 直接返回该值 → `'false'` 为非空字符串即真值 → `DEBUG=True`。`.env.example:32` 正是指导这样写。
- 影响：按官方示例部署的生产环境 DEBUG 全开，错误页泄露配置/SQL/后端路径。
- 修复：ENV 加载对布尔语义键归一化（false/0/no/off→False）+ 启动自检。一行级修复，最优先。

## 2. P1

### 安全类

#### P1-1 Celery 反序列化条件性 RCE：pickle + 可预测默认 HMAC 键【✅亲验】
- `apps/ops/celery/hmac_signed_serializer.py:8-16`：默认键=`固定前缀+主机名`（可推导），payload 走 `pickle.loads`；`maxkb/settings/celery.py:76` accept_content 含明文 `json` 可绕过签名机制。
- 影响：能连上 Redis broker 的攻击者可伪造签名任务，worker 反序列化即任意代码执行。
- 修复：未显式注入随机 HMAC 键拒绝启动（fail-closed）；accept_content 仅保留签名格式；长期迁离 pickle。

#### P1-2 SECRET_KEY 硬编码兜底【✅亲验】
- `maxkb/settings/base.py:21`：仓库公开常量作 fallback → 会话伪造 / mk_file_auth 文件票据可伪造。
- 修复：`DEBUG=False` 且缺 Key 时拒绝启动。

#### P1-3 hr_members 回退死代码 → 全平台用户目录泄露 + 成员校验失效【C 轮首发，✅亲验全链路】
- `apps/hr/serializers/access.py:29-31` ← `apps/users/serializers/user.py:593-629`。本 fork 从不定义 `MODEL_HANDLES` → `get_model("workspace_user_role_mapping")` 恒 None → 内核恒走 fallback 返回**全平台非管理员用户**（非空）→ 「防跨租户枚举」的本工作区回退永不执行。
- 影响：① VIEWER 经 `GET /hr/members` 枚举全实例用户；② `set_access` 与两处 `_interviewer_user_id` 成员校验整体失效，可把任意平台用户指派为面试官并接触候选人信息。
- 修复：内核成员缺失时返回空/报错，hr_members 用「HrAccess ∪ 已指派 owner/interviewer」交集兜底；补不 patch 的回归测试（现 tests.py:1070 patch 假场景）。

#### P1-4 knowledge 批量操作 IDOR 家族【A 轮】
- `apps/knowledge/serializers/document.py:1444-1647,462-553`、`paragraph.py:628-651`：批量删除/迁移/导出的 id_list 不校验 workspace 归属 → 跨租户读写删；`paragraph.py:265,291-302` 带 problem_list 编辑必 500。（建议按 A 轮报告逐条复核修复。）

#### P1-5 embed.js 反射型 JS 注入/XSS【A 轮】
- `apps/chat/serializers/chat_embed_serializers.py:69-106` + `template/embed.js:31,65`：host 含换行打断 JS 字符串、query 未编码、insertAdjacentHTML 还原实体；端点无需有效 token。
- 修复：host allowlist、`urllib.parse.quote`、模板改 DOM API。

#### P1-6 admin 调试对话端点无权限校验【A 轮】
- `apps/application/views/application_chat.py:140-154`：仅 TokenAuth，任意登录用户可以 debug 模式用任意活跃 chat_id 跨工作区使用模型/知识、绕过配额；缓存 miss 另有 None 崩溃（chat.py:167）。

#### P1-7 匿名密码重置无防护【A 轮】
- `apps/users/views/user.py:301-319`：无限流 + 非加密随机验证码 + CheckCode 预言机。修复：限流 + 统一错误 + secrets 模块。

### 功能断裂类（0030 删列残留，三方一致确认）

> 根因：迁移 0030 物理删除 Candidate 13 列 + DROP CandidateSkill 后未清扫引用方，配套回归测试被批量掏空成 `assertTrue(True)`（tests.py:592/1192/1576/5828 等 ~30 处）。恢复真实断言应与修 bug 同优先级。

- **P1-8 city 过滤必 500**【✅实测复现】：`application_service.py:580-584` 引用已删列；入口 `application_views.py:68` 直传 query_params；文档化参数。→ 删死分支或参数白名单。
- **P1-9 CSV 导入整体崩溃**【✅亲验】：`import_service.py:60-92` 传 13 个已删字段 + 调 5 个已删除 helper → TypeError 500；模板仍下发旧表头。同根因：`hr_agent_probe.py:123`、`eval_screening.py:55,177-208`、`import_resume_dataset.py:253`（A 轮）。→ 收敛三字段重写或下线 410。
- **P1-10 similar_jobs 击穿 JD/Copilot**【✅运行验证 AttributeError】：`similar_jobs.py:21,24`；相似职位存在 ≥1 条 HIRED 申请即崩 → 整个 run FAILED，有录用历史的租户内 JD 起草与 Interview Copilot 功能性死亡。→ 画像改 raw_text 聚合或返回 `(count,None,[])`；恢复单测。
- **P1-11 edit_job 直改 CLOSED 绕过两阶段关闭**【C 轮首发，✅亲验】：`recruitment.py:732-741` 只挡 CLOSED→其他反向；ACTIVE 申请不关、Offer 不撤、无事件；此后 send/accept offer 照常 →「已关职位上 HIRED」。→ edit_job 拒绝迁往 CLOSED 或复用 STRICT/BULK 级联。

### 性能宣称失实

- **P1-12 raw_text 承诺的 pg_trgm GIN 索引不存在**【C 轮首发，✅全仓 grep 零匹配】：0029 仅 AddField；HANDOFF.md:134 与 PRODUCTION-GAP-ANALYSIS 宣称失实。`resume_search.py:190,394`、`recruitment.py:403,1099` 及共享 Paragraph 表 icontains 全部顺序扫描。→ 新迁移建 `GIN (UPPER(col) gin_trgm_ops)` 表达式索引；文档对账。

### 数据合规类

- **P1-13 简历 TTL 清理漏删流转日志，未脱敏原文永久留存**【A 轮】：`task/resume.py:41-60` 不调 delete_flow_logs，而 EXTRACT/SANITIZE/SPLIT 节点把简历全文写入 ResumeFlowLog（`task/resume.py:74-77,140-143`、`resume_index.py:105-121`）。违反 PRD §4.4/§7。→ TTL 联动清 flow log 或日志只存摘要。
- **P1-14 0030 无数据归档即物理删除含知情同意字段**【C 轮】：consent_status/version/collected_at 等 13 列一次性丢弃，合规证据链断裂，reverse 仅能回加空列。→ 导出留痕签核或快照进审计。

## 3. P2（27 项，按主题分组）

### A. 出站集成与边界
1. **oss SSRF 可回显内网响应**【A，✅亲验核心行】：`apps/oss/serializers/file.py:365-380` 客户端 URL、`verify=False`、text 体回显、先下载后限流；匿名 embed 可达 `/chat/api/oss/get_url/<id>`。→ 私网 CIDR 黑名单 + 仅 http(s) + 禁回显 text + 流式限额。
2. **HR 入职交接 Webhook SSRF + 明文外发**【C，✅亲验】：`offer.py:439-455,564-581` URL 仅限长度≤512，urlopen 直连（跟重定向），payload 含明文手机/邮箱，accept/retry 自动触发、retry 无上限。→ https 强制 + 私网段拒绝 + 异步投递 + attempts 上限。
3. **模型引用不校验 workspace 归属**【A/C 一致】：`models_provider/tools.py:112-121` slim 内核授权机制缺位致条件短路放行他租户模型，消耗其凭证。→ mismatch 拒绝。
4. **网络边界配置过宽 + 默认口令族**【B】：ALLOWED_HOSTS=['*']（base.py:26）、信任 X-Forwarded-Proto、Config.defaults 硬编码 DB/Redis 口令、DB_SSLMODE 不校验、cookie 安全标志未设。→ 关键项 fail-closed。
5. **匿名 chat token 永不过期**【A】：`chat_authentication.py:35,43` 加 max_age。
6. **会话详情缺 chat_user 属主绑定（同应用 IDOR）**【A】：`chat_record.py:182-201`+`application_chat_record.py:65-112`。

### B. Agent 运行时（均为 C 轮首发）
7. **pydantic Screening 模块级全局证据白名单**：并发 run 互相污染、防编造校验失效（`runner_pydantic.py:69,248`）。→ contextvars/deps 传递。
8. **Copilot/Sourcing 无证据 paragraph_id 服务端校验**：「引用忠实度 ≥95%」只在 Screening 成立（`copilot_runner.py:84-91`、`sourcing_runner.py:94-100`）。
9. **并发/速率护栏 check-then-write 竞态**；手动 API 请求线程内同步跑 LLM（含退避 sleep）；SKIPPED 计入速率分母（`agents/base.py:20-35`、`agent_views.py:90-98`）。→ Redis 锁原子化 + 手动触发异步化。
10. **propose() 同目标一刀切过期**：零风险草稿挤掉待决决策提案；采纳率把 EXPIRED 计入分母系统性稀释；分数带 60/80 与 HOLD=48 漂移（`proposals.py:35-40`、`agent_stats.py:70-74,15-23`）。
11. **workbench retry_run 固定走 legacy runner**，绕过 USE_PYDANTIC_AI 开关（`agent_workbench.py:13-17,285-333`）。
12. **token 记账失真**（升列于此因影响成本核算）：多次重试只记最后一次、FAILED 运行零记录（`runner.py:185-191,403-422`）。

### C. Offer / Interview 状态一致性
13. **Offer 并发窗口**【A #13 + C】：无活跃 Offer 条件唯一约束；withdraw 用事务外旧快照整行 save() 可把 ACCEPTED 覆写为 WITHDRAWN 而 Application 已 HIRED（比双时间戳更严重）；accept 的 handoff 创建在事务外不可恢复。→ select_for_update + 条件 UPDATE 乐观守卫 + 部分唯一索引 + handoff 入事务幂等。
14. **update_offer 审批后可改薪金不重置审批**【C】：`offer.py:192-205` → 已 APPROVED 只读或改动即重置 PENDING。
15. **OFFER 阶段终态缺 SENT Offer 前置守卫**【B P2-2 + C】：文档要求 vs `_terminal` 未查 Offer 表，SENT 滞留在途。
16. **update_interview 零审计任意改写 + 反馈可重复提交翻转结论**【C】：`recruitment.py:1175-1198,1297-1313`；面试反馈原文还写入不可清除的审计日志（A #14 后半）。→ 迁移矩阵 + 审计 + 一次性提交。
17. **_terminal 幂等键对顺序重试失效**【C】：status 检查先于幂等事件查找（`application_service.py:346-355`；move_stage 300-309 顺序是对的）。

### D. 检索与数据层
18. **结构化路跨租户段落全表扫描**【B P2-1 + C】：`resume_search.py:398-400` Paragraph 查询无工作区前置限定（keyword 腿 183-186 是对的写法）。
19. **hard_slots=False 写死后 meta 仍上报槽位**【C，承 B P3-3 升格】：预筛死代码、wrapper 过滤恒真桩，违反 RAG-V2-DESIGN G1；调用方误以为年限/学历/城市已生效（`resume_search.py:106-108,650-652,683`）。→ meta 如实标注 disabled 或重建硬条件。
20. **scope_document_ids 巨型 IN + 内部 UUID 泄露进响应**【A 补充】：`resume_search.py:614-618,644-645` 显式选库时全库 id 物化进内存与响应 meta。
21. **简历重建索引「删旧→建新」无外层事务**【A 补充】：中途失败留悬空 document_id 该简历永久不可搜（`resume_index.py:122-129,208-214`）。
22. **Document.delete 无 hr_protected 校验**【C】：常规文档接口可删简历语义索引 Document，ResumeFile.document_id 悬空、语义检索静默失效（`knowledge/serializers/document.py:820-837`）。
23. **ResumeFile.save() 总库引导并发不安全 + 双实现漂移**【三轮一致】：查后写撞唯一约束上传 500；每次 save 重复引导查询（`models/recruitment.py:273-299`）。→ 收敛服务层 get_or_create。
24. **Screening 信号事务内 delay 缺 on_commit**【A #16 + C】：初筛触发可能静默丢失/幻影分发（`signals.py:15-35`、`runner.py:467-471`）。
25. **Celery 异步管线完整性**【A #16】：embedding 任务无 retry/acks_late（STARTED 永久卡死）、post_delete 兜底信号缺失（旁路删除残留可检索向量 ≤30 天）。
26. **存储临时文件泄漏**【A #18 + C】：`services/storage.py:39-49` 每次 open() 物化完整简历到 tmp 不清理；`views/recruitment.py:191-199`/`offer_views.py:100-112` 上传临时文件异常路径残留 /tmp（PII 明文）。→ try/finally 统一清理。
27. **hr_agent_probe 凭据落库副作用**【A】：`hr_agent_probe.py:58-90` 崩溃前把环境凭据加密写回全工作区同名生产模型行（按 model_name 匹配无 workspace 过滤）。

### E. 观测/日志/前端
28. **LOG_LEVEL 默认 DEBUG 致 SQL 参数（手机号/邮箱）落日志**【B P2-3】：`conf.py:133` + `settings/logging.py:99-103`；且 logging 无系统性 PII 脱敏 filter【B P2-6】。→ 生产 INFO + 脱敏 Filter。
29. **前端权限错位**：`/hr/jobs/new` 放行 OPERATOR 但后端 ADMIN，白填整表单必 403（`ui/src/router/modules/hr.ts:75`）。
30. **axios 5xx/网络错误零反馈**：拦截器只处理 ECONNABORTED/404/401/403，叠加页面空 catch（`ui/src/request/index.ts:63-89`）。
31. **lint 债务 280 项含 F821×3/E722×6**【A/B】：F821 是复活即炸的死代码（common.py:219,284,290 未 import io）；E722 吞 KeyboardInterrupt。130 项可 --fix。

## 4. P3（择要，~20 项）

- **死代码/残留键**：split_resume_with_skills 的 skills 解析链（prompt 已撤回恒空）、extract_skills_llm 孤儿、parse_resume_text 返回残键、前端 Sourcing skills 标签块/constants.ts 合规常量/sourcing_runner 字段透传三处跨端死链、chat 未挂载 ResourceProxy/UploadFile（SSRF 形态防误挂载）、get_job 死代码双查询。
- **加固**：ILIKE `%`/`_` 未转义（无注入）；VIEWER 联系方式子串存在性探测 oracle；Offer 附件无类型白名单；未处理异常原文直返客户端 + error_message 对 VIEWER 可见；search_to_llm 缺防御性掩码（入库侧有双保险）；附件下载路径无 workspace 包含性断言（纵深）；email N+1（每页 ~101 查询）。
- **观测**：新版 runner provider 异常不重试（五 Agent 重试语义不一）；sourcing 工具轨迹计时器恒≈0ms；edit_job 审计无 before/after、headcount 可低于在招数；面试时间字段零校验非法值 500；_write_search_audit 吞异常。
- **杂项**：router.push('/404 ') 尾随空格；前端 workspace 回退 'default' 必败请求产生审计噪音；0025 注释 DEFERRABLE 断言失实 + replay 取 first() 可能错配 reapply；current_page=0 负切片 AssertionError；ApplicationEvent.idempotency_key 默认空串+唯一约束陷阱；token 存 localStorage 评估 httpOnly；GeneratorExit后再yield RuntimeError（base_chat_step.py:282-319）。

## 5. 通过项（抽查验证为健全的设计）

- **多租户隔离**：83 条 HR 路由认证装饰器全覆盖；IDOR 取数一致带 workspace 过滤、跨租户统一 404 泛化；VIEWER 脱敏在服务端做。
- **PII 主链路**：mask_pii 先于任何 LLM + scan_residual_pii 二次拒收；LLM 投影剔除联系方式；生产活跃路径无未掩码简历文本直达 LLM；检索 SQL 全参数化。
- **ATS 状态机**：ACTIVE 部分唯一约束（DB 级）、select_for_update + 事务内二次校验 + 幂等事件；HIRED 仅经 accept_offer 同事务触发；round_no 服务端生成 + DB 唯一；close_job 对 job 与 applications 同时加锁。
- **Agent 红线**：唯一写出口 Proposal；accept 经命令层不绕状态机；JOB 草稿采纳仅 ADMIN；scope.py 库范围校验严密且检索侧独立二次校验；知识库白名单服务端强制排除 hr_protected。
- **其他**：注销双入口权限/确认/活跃守卫完备；认证主干 deny-by-default、PBKDF2；文件解析无 XXE/路径穿越；前端 HR 页面零 v-html、构建 base 配置正确。

## 6. 修复路线图（三轮合并排序)

1. **当天可完成的小改**：P0-1 布尔归一化；P1-2/P1-1 fail-closed（SECRET_KEY、HMAC 键 + accept_content 收窄）；P1-3 hr_members 交集兜底；P1-11 edit_job 收口。
2. **本周**：0030 清剿四件套（city/CSV/probe/eval 数据集脚本）+ similar_jobs 兼容 + **恢复全部 stub 测试为真实断言**；webhook 与 oss SSRF 加固；trgm 表达式索引迁移；Offer 条件唯一约束 + withdraw 乐观守卫 + 审批后禁改；on_commit；Document 层 hr_protected。
3. **随后**：Agent 证据校验统一、护栏原子化、采纳率口径修正、retry 路由统一、双轨 runner 收敛为一；knowledge 批量 IDOR 家族逐条修复复核；日志级别 + PII 脱敏 Filter；TTL 联动清 flow log。
4. **对账与长期**：HANDOFF/RAG-V2-DESIGN 失实宣称修订；recruitment.py(1313 行)/resume_search.py(1012 行)拆分；ruff --fix 清理并在 pyproject 固化豁免口径。
