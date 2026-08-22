# 全项目代码审查报告 B 轮：核心链路人工深审（2026-08-22）

> 配套文件：`docs/CODE-REVIEW-2026-08-22.md`（A 轮，4 并行代理全仓扫描）。本轮为独立第二意见：
> 静态检查 + 后端全量测试实跑 + 核心链路逐行人工审查（ATS 主链 / 简历 RAG 检索 / Agent 提案审批 /
> 租户注销 API / 配置安全基线 / 前端抽查），所有结论均经实际代码阅读或运行验证。
> 审查对象 commit `54c8cd2`，工作树干净。本次审查只读，未修改任何业务代码。

## 0. 结论速览

| 级别 | 数量 | 要点 |
|---|---|---|
| P0 | 1 | ENV 模式 `MAXKB_DEBUG=false` 被当作 True，生产 DEBUG 开启（**实测复现**） |
| P1 | 4 | SECRET_KEY 硬编码兜底；Celery pickle+可预测 HMAC 键；`?city=` 已删列查询必现 500；0030 删列残留致 CSV 导入崩溃与 similar_jobs 击穿（A 轮发现，本轮复核证实） |
| P2 | 7 | 跨租户段落扫描；OFFER 终态守卫缺失；SQL 全参数落日志；lint 债务 280（含 F821）；网络边界配置过宽等 |
| P3 | 8 | ResumeFile.save 边角、事件幂等键陷阱、meta 槽位误导等 |

### 对 A 轮报告关键声明的交叉验证结果

| A 轮声明 | 本轮复核 |
|---|---|
| `import_service.py:70-89` 引用 13 个已删字段 | ✅ 属实（current_city/target_city/highest_degree/years_experience/skills/source… 全在 create kwargs 中） |
| `similar_jobs.py:21,24` 引用已删字段 | ✅ 属实（`candidate.years_experience`、`candidate.skills`） |
| 约 20 处回归测试被 `# 0030 stub` 掏空 | ✅ 属实（tests.py:592/1192/1196/1576 等多处 `assertTrue(True)`）——**528 绿灯基线含空洞，测试通过≠功能完好** |
| Celery pickle + 可猜 HMAC 键 | ✅ 属实（详见 P1-3） |
| SECRET_KEY 硬编码默认 | ✅ 属实 |

> ⚠️ 重要修正：本报告 v1 曾写「后端全量 528 tests OK 作为回归护航」——复核 A 轮发现后确认其中部分
> 0030 相关用例已被 stub，该基线对「删列残留」类回归**无保护力**。

---

## 1. 运行时验证

```bash
uv run python manage.py test hr.tests application.tests knowledge.tests \
  models_provider.tests ops.tests common.tests --keepdb   # Ran 528 tests in 21.375s — OK（含 0030 stub 用例）
.venv/bin/python manage.py check                            # 0 issues
.venv/bin/ruff check apps/hr                                # All checks passed
```

ruff 全仓 280 项错误分布：apps/common 134、system_manage 30、application 28、knowledge 25、models_provider 19、users 16、其余零散；错误码 F401×79 / F403×76 / F405×57 / F841×52 / F541×6 / E722×6 / F821×3 / E731×1 / E701×1。

---

## 2. 发现清单

### P0

#### P0-1 ENV 模式布尔配置解析缺陷：`MAXKB_DEBUG=false` 实际开启 DEBUG【实测复现】

- **位置**：`maxkb/conf.py:224-248`（load_from_env 原样存字符串）+ `maxkb/conf.py:52-53`
- **证据**：
  ```python
  config = {key.replace("MAXKB_", ""): os.environ.get(key) for key in keys if key.startswith("MAXKB_")}
  def get_debug(self) -> bool:
      return self.get("DEBUG") if "DEBUG" in self else True
  ```
  实测输出：`MAXKB_DEBUG=false -> 'false' | truthy: True`。
- **影响**：`.env.example:32` 正是指导部署写 `MAXKB_DEBUG=false`——按官方示例部署的生产环境 DEBUG 全开，错误页泄露配置/SQL/后端路径（PRD §7 信息泄露门槛失守）。
- **修复建议**：ENV 加载时对布尔语义键归一化（`false/0/no/off → False`）；补启动自检。

### P1

#### P1-1 SECRET_KEY 硬编码回退

- **位置**：`maxkb/settings/base.py:21`
- **证据**：`SECRET_KEY = CONFIG.get("SECRET_KEY") or 'django-insecure-zm^1_^i5)...'`（仓库内公开常量）
- **影响**：未注入 `MAXKB_SECRET_KEY` 的部署共享公开密钥 → 会话伪造 / mk_file_auth 文件票据可伪造（A 轮补充）。
- **修复建议**：`DEBUG=False` 且缺 Key 时 fail-closed 拒绝启动。

#### P1-2 Celery 反序列化链条件性 RCE：pickle + 可预测默认 HMAC 键【核实源码】

- **位置**：`apps/ops/celery/hmac_signed_serializer.py:8-11,13-24`；`maxkb/settings/celery.py:74-76`
- **证据**：
  ```python
  _local_secret_key = os.environ.get('MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY',
      'default_hmac_signed_serializer_secret_key:' + os.getenv('MAXKB_VERSION', socket.gethostname()))
  ... pickle.loads(payload) ...
  CELERY_accept_content = ['json', 'hmac_signed_serializer']
  ```
  默认键 = 固定前缀 + 主机名（日志/监控常泄露主机名）。任务体唯一防线是 HMAC 签名。
- **影响**：能连上 Redis broker 的攻击者可推导密钥、伪造签名任务 → worker 反序列化即任意代码执行。`.env.example:24` Redis 空密码示例放大暴露面。A 轮另指出 accept_content 含明文 json 可绕过签名机制。
- **修复建议**：未显式注入随机 HMAC 键即拒绝启动；accept_content 仅保留签名格式；长期迁离 pickle。

#### P1-3 城市筛选引用已删除列：`?city=` 参数必现 FieldError 500

- **位置**：`apps/hr/services/application_service.py:582-584`；入口 `apps/hr/views/application_views.py:68`
- **证据**：`Q(candidate__current_city__icontains=city) | Q(candidate__target_city__icontains=city)` —— 两列已在迁移 `0030` 物理删除；`ApplicationPageAPI.get` 把 `request.query_params` 原样透传。
- **影响**：`GET /hr/applications/page/1/10?city=x` 即 500。
- **修复建议**：移除死分支；查询参数白名单化。

#### P1-4 0030 删列残留（承 A 轮，本轮复核证实）

- **位置**：`apps/hr/serializers/import_service.py:70-89`（CSV 导入 create 引用 13 个已删字段，任何导入请求 500）；`apps/hr/services/similar_jobs.py:21,24`（有 HIRED 历史的租户内 similar_jobs 必抛 AttributeError → JD 起草/Sourcing 等 Agent run FAILED）；同根因还有 `hr_agent_probe.py`、`eval_screening.py`、`import_resume_dataset.py`（见 A 轮 #7/#8/#10）。
- **影响**：两条主流程（批量导入、Agent 录用画像）在真实数据下不可用，且被 stub 测试掩盖。
- **修复建议**：全仓清剿 `current_city|target_city|years_experience|highest_degree|candidate.skills` 引用；恢复被 `# 0030 stub` 掏空的测试并补真实断言。

### P2

#### P2-1 简历检索模式 B 结构化路跨租户段落全表扫描

- **位置**：`apps/hr/services/resume_search.py:398-400`
- **证据**：`Paragraph.objects.filter(content__icontains=term, is_active=True)` 无 workspace/knowledge 限定，扫全部租户段落后靠 `ResumeFile.filter(workspace_id=...)` 兜底丢弃。
- **影响**：无数据泄露，但随数据增长线性恶化；与同文件 `_keyword_recall_docs:183-186` 的正确限定写法不一致。
- **修复建议**：结构化路复用 keyword 腿的文档集限定。

#### P2-2 OFFER 阶段终态迁移缺少 SENT Offer 前置守卫（目标设计偏差）

- **位置**：`apps/hr/services/application_service.py:338-390`（`_terminal`）
- **证据**：`docs/ATS-STATE-MACHINE-V2.md §2.1` 要求 REJECTED/WITHDRAWN「源为 OFFER 阶段且有 SENT Offer 时先处理 Offer」；代码仅校验原因枚举。
- **影响**：OFFER 阶段可直接 REJECT/WITHDRAW，SENT Offer 悬挂成无主工件。
- **修复建议**：存在 `status=SENT` Offer 时要求先撤回或 ADMIN 显式联动 WITHDRAWN。

#### P2-3 SQL 全参数落日志（PII 门槛冲突）

- **位置**：`maxkb/conf.py:133`（LOG_LEVEL 默认 DEBUG）+ `maxkb/settings/logging.py:99-103`
- **影响**：`django.db.backends` DEBUG 将含手机号/邮箱的 SQL 参数写入 `logs/maxkb.log`，违反 PRD §7。
- **修复建议**：生产 LOG_LEVEL 默认 INFO，或对 django.db.backends 单独限级；配合 A 轮 P2-2 的脱敏 filter。

#### P2-4 内核 lint 债务 280 项，含 3 处 F821 未定义名

- **位置**：`apps/common/utils/common.py:219,284,290` 用 `io.BytesIO` 未 `import io`（当前无调用方的死代码，复活即 NameError）；E722 ×6（`main.py:33`、`apps/ops/celery/utils.py:45`、`apps/common/management/commands/services/services/base.py:104,142,166`）吞 KeyboardInterrupt/SystemExit。
- **修复建议**：清理 F821/E722；其余 F401/F841 批量 fix 或在 pyproject 写明豁免口径。

#### P2-5 网络边界配置过宽 + 默认口令族

- **位置**：`base.py:26`（ALLOWED_HOSTS=['*']）、`:197`（信任 X-Forwarded-Proto）；`conf.py:31,42`（Config.defaults 硬编码 `Password123@postgres`/`Password123@redis`，缺单项静默回退）；`conf.py:61-63`（DB_SSLMODE 透传无校验，默认不启用 TLS）；cookie 安全标志未显式设置；无 CsrfViewMiddleware（自研 Header-token 认证缓解，前提需文档固化）。
- **修复建议**：关键安全项缺失 fail-closed；SSLMODE 白名单校验；显式声明 SESSION/CSRF cookie 标志。

#### P2-6 日志无系统性 PII 脱敏 filter

- **位置**：`maxkb/settings/logging.py` 无脱敏 filter；异常仅本地轮转存储。
- **修复建议**：logging.Filter 对 phone/email 掩码（PRD §7 门槛）。

#### P2-7 匿名密码重置无防护（承 A 轮 #6，本轮未复测）

- **位置**：`apps/users/views/user.py:301-319`
- **修复建议**：限流 + 统一错误响应 + `secrets` 模块生成验证码。

### P3（择要）

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| 1 | `apps/hr/models/recruitment.py:273-299` | `ResumeFile.save()` 每次 save 追加 2-4 条查询；`globals().get()` 取后定义类；并发首次建档可能双建总库撞唯一约束 | 移服务层；get_or_create 建总库 |
| 2 | `recruitment.py:543-553` | `ApplicationEvent.idempotency_key` 默认空串 + 唯一约束：未来直接 create 同类型空键事件第二次会 IntegrityError | save 校验或改 null |
| 3 | `resume_search.py:106-108,552-559` | 0030 后硬条件匹配恒真桩，meta 仍透出 years/degree/cities 槽位且 wrapper 过滤为 no-op，误导用户 | meta 如实标注 disabled |
| 4 | `resume_search.py:1001-1012` | `_write_search_audit` 吞审计异常 | 至少 log warning |
| 5 | `application_service.py:593-594` | `current_page=0` 负切片 → AssertionError 500 | 入口钳制 page≥1 |
| 6 | `ui/src/stores/modules/login.ts:16-38` | token 存 localStorage（v-html 仅 4 处上游动态表单组件，HR 页面未见危险渲染） | 评估 httpOnly cookie |
| 7 | knowledge 批量 IDOR 家族 / embed.js 注入 / SSRF / admin debug 端点无权限（承 A 轮 #1/#2/#3/#12） | 本轮未逐条复测，建议按 A 轮报告优先处理 | 见 A 轮报告 |
| 8 | Offer 并发窗口（承 A 轮 #13：withdraw 旧快照整行 save 可覆盖 ACCEPTED） | 建议 withdraw/accept 统一 select_for_update + DB 状态条件 UPDATE | 见 A 轮报告 |

---

## 3. 做得好的（保持项）

- **数据完整性**：Application「同候选同职位至多一条 ACTIVE」为 DB 级部分唯一约束（0019），create 捕获 IntegrityError 映射业务异常；JobStage/Offer 版本/Interview 轮次均有唯一约束。
- **并发正确性**：move_stage/_terminal/restore/close_job/Proposal.accept 均 `select_for_update` + 事务内二次校验 + 幂等键；close_job 对 job 与 applications 同时加锁。
- **Proposal 单一写出口成立**：accept 经 `ApplicationService` 命令执行不绕过状态机；JOB 草稿采纳仅 ADMIN 且只写文本字段；INTERVIEW 提案仅确认不落库；双重 stale 失效校验。
- **权限层级**：Copilot 触发在 runner 内校验本人面试官或 OPERATOR+（copilot_runner.py:132-139）；工作台/证据接口 OPERATOR+；VIEWER 在搜索结果/提案输出/事件输出一致脱敏。
- **范围校验贯穿**：`resume_database_ids`（workspace+ACTIVE+≤50）贯穿召回→rerank→聚合→keyword 腿；document_ids/candidate_id 交叉校验防作用域泄露。
- **输入卫生**：top_k∈[1,20]、recall_k/similarity clamp 防 PG LIMIT 报错；SEARCH 审计不存查询原文。
- **注销 API**：工作区管理员 + `confirm_workspace_id` 服务端强校验（workspace_offboarding.py:70-71）。
- **认证面**：Header-token 认证使 CSRF 风险低；密码哈希 PBKDF2 默认迭代；YAML 配置缺失 fail-fast。

## 4. 未深审区域

`serializers/recruitment.py`（1313 行）全量、agents 各 runner 内部 PII 投影细节、offboarding service 清理实现细节、前端页面级深度审查、apps/knowledge 与 apps/common 内核——两轮审查合并后的剩余盲区，建议按 A 轮报告的 SSRF/embed.js/IDOR 清单优先复核。

## 5. 建议修复顺序

1. **P0-1**（一行布尔归一化）
2. **P1-1/P1-2**（两处 fail-closed：SECRET_KEY、HMAC 键 + accept_content 收窄）
3. **P1-4**（0030 删列残留清剿 + 恢复 stub 测试——恢复测试真实断言后再谈基线可信）
4. **P1-3**（删 city 死分支）
5. **P2-2**（Offer 守卫）→ P2-3/P2-6（日志级别与脱敏）
