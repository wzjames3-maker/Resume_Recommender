# 数据生命周期与简历治理设计（A4）

## 目标

补齐 PRD 第 7、9 节剩余上线门槛：候选人合规元数据（来源与告知）、候选人删除/匿名化流程、未关联简历 30 天 TTL 清理、候选人删除时简历联动清理，以及受控字段白名单导出。数据主体请求（撤回/更正/删除）在 A4 通过「删除/匿名化」流程承接，撤回联系偏好通过 `contact_preference` 表达。

## 范围

### 范围内

- `Candidate` 合规元数据：`source_type`、`source_detail`、`collected_at`、`consent_status`、`consent_version`、`contact_preference`。
- 候选人删除/匿名化：`DELETE` 语义的软删除；清除 PII、保留匿名历史行与审计；进行中指派拒绝删除。
- 简历联动清理：候选人删除时删除其简历文件与 `ResumeFile` 记录并审计。
- 未关联简历 TTL：Celery 定时任务每日清理 `create_time` 超过 30 个自然日且未关联候选人的简历（删文件、记录、审计）。
- 受控导出：HR ADMIN 导出候选人 CSV，字段白名单（不含手机/邮箱等联系方式），写 `EXPORT` 审计。
- 前端：候选人合规元数据表单、删除入口（ADMIN）、导出入口（ADMIN）。

### 不在范围内

- 字段级加密存储、密钥管理与 TLS 配置（部署层，A5 验证）。
- 批量导入 CSV（B 阶段）。
- 候选人更正请求的独立审批流（本阶段由编辑 + 审计覆盖）。
- 租户注销与全量数据返还/删除（企业部署协议层）。

## 数据模型

### Candidate 新增字段

| 字段 | 类型 | 规则 |
|---|---|---|
| `source_type` | CharField(20)，choices | 复用 `ResumeChannel` 枚举（`REFERRAL`/`JOB_SITE`/`HEADHUNTER`/`CAMPUS`/`OTHER`），默认 `OTHER`。 |
| `source_detail` | CharField(128, blank) | 渠道详情文本。 |
| `collected_at` | DateTimeField(null=True, blank=True) | 收集日期。 |
| `consent_status` | CharField(16)，choices | `UNKNOWN` / `NOTIFIED` / `CONSENTED` / `NOT_REQUIRED`，默认 `UNKNOWN`。 |
| `consent_version` | CharField(32, blank) | 告知版本号。 |
| `contact_preference` | CharField(16)，choices | `EMAIL` / `PHONE` / `NO_CONTACT` / `UNSPECIFIED`，默认 `UNSPECIFIED`。 |

### CandidateStatus 新增 `DELETED`

- `DELETED`：匿名化后的历史行。默认列表与检索过滤（`status=ACTIVE/ARCHIVED`）；详情仅管理员可见。
- 删除流程（`PUT /candidates/{id}/delete`，仅 ADMIN）：
  1. 存在进行中指派（`ACTIVE_ASSIGNMENT_STATUSES`）→ 400「Candidate has an active assignment」。
  2. 存在 `HIRED` 指派 → 400「Candidate is hired, cannot delete」。
  3. 清空 PII：`name` → `已删除候选人`、`email/phone/current_city/target_city/highest_degree/years_experience/skills/source/note` 置空，`status=DELETED`。
  4. 删除候选人简历：删除文件与 `ResumeFile` 记录（存在 `candidate` 关联），写 `RESUME_DELETE` 审计。
  5. 写 `DELETE` 审计（object_type=CANDIDATE, result=SUCCESS）。
- 终态指派（`REJECTED`/`WITHDRAWN`/`CLOSED`）保留为匿名引用（候选人为 `DELETED` 行）。

## 简历 TTL 清理

- 任务：`apps/hr/task/resume.py` 新增 `cleanup_orphan_resumes`（Celery task，`@shared_task` 或与既有任务同风格）。
- 逻辑：删除 `candidate__isnull=True` 且 `create_time < now - 30 天` 的 `ResumeFile`；对每条记录删除物理文件（`os.path` 或项目既有文件删除工具）并写 `RESUME_DELETE` 审计（`detail` 注明 TTL）。
- 调度：`django_celery_beat` 的 `PeriodicTask`，每日执行；在 `apps/hr/apps.py` ready 中幂等创建（`get_or_create`，crontab 每日 03:00），名称 `hr-cleanup-orphan-resumes`。
- 测试：直接同步调用任务函数验证（不依赖 beat 调度）；构造 31 天前未关联简历被清理、30 天内保留、已关联不被清理。

## 受控导出

- API：`POST /hr/export/candidates`（仅 ADMIN），请求体 `{"filters": {...}}` 复用候选人列表筛选参数；返回 CSV 文件流（`Content-Disposition` 附件）。
- 字段白名单（不含联系方式）：`name`、`status`、`current_city`、`target_city`、`highest_degree`、`years_experience`、`skills`、`source_type`、`source_detail`、`collected_at`、`consent_status`、`contact_preference`、`create_time`。
- 写 `EXPORT` 审计（object_type=CANDIDATE, detail 记录条数与导出人）。
- 列表与导出都遵守角色（ADMIN 明文；其他角色无导出入口）。

## API

统一前缀：`/admin/api/workspace/{workspace_id}/hr`。

| 方法 | 路径 | 用途 | 权限 |
|---|---|---|---|
| PUT | `/candidates/{candidate_id}` | 编辑候选人（含合规元数据字段） | OPERATOR/ADMIN |
| GET | `/candidates` | 列表（默认过滤 `DELETED`） | 任意 HR |
| GET | `/candidates/{candidate_id}` | 详情（`DELETED` 仅 ADMIN 可见） | 任意 HR |
| PUT | `/candidates/{candidate_id}/delete` | 删除/匿名化 | ADMIN |
| POST | `/export/candidates` | 受控导出 CSV | ADMIN |

跨工作区一律 404。非法枚举 400。

## 前端

- 候选人表单：新增来源类型/详情、收集日期、告知状态/版本、联系偏好字段。
- 候选人操作列：「删除」按钮（ADMIN 可见，确认弹窗提示删除即匿名化且删除简历）。
- 列表页：「导出」按钮（ADMIN 可见，调用导出接口下载 CSV）。

## 测试

- 合规元数据：创建/编辑候选人保存各字段；非法枚举 400。
- 删除：进行中指派拒绝（400）；HIRED 拒绝（400）；删除后 PII 清空、状态 DELETED、默认列表隐藏、简历文件与记录删除并审计；终态指派保留匿名引用；非 ADMIN 403。
- TTL：31 天前未关联简历被清理、30 天内保留、已关联不被清理、审计写入。
- 导出：ADMIN 成功导出 CSV（含白名单字段、不含手机/邮箱）、审计写入；非 ADMIN 403。
- 回归：既有 hr 测试全部通过（删除为新增语义不影响存量）。

## 验收

HR 全量测试 PASS、`manage.py check` 无问题、`makemigrations --check --dry-run` 无漂移、前端 `vue-tsc` 与 admin/chat 双构建 PASS。

## 取舍

- 删除采用匿名化软删除而非物理删除：保留匿名统计与审计引用，符合保留期限原则且实现可控。
- 导出固定字段白名单且不含联系方式：最小外流面，满足「默认禁止通用批量导出」的例外定义。
- TTL 使用 daily beat 而非实时钩子：实现简单、可测试；30 天窗口内延迟清理可接受。
- 合规元数据均可选填：避免破坏既有录入体验；「不明来源不得录入真实 PII」由 A3 授权与 A4 导出/审计共同支撑。
