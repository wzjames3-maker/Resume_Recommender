# HR 访问控制与操作审计设计（A3）

## 目标

补齐 PRD 第 3、7 节的生产上线门槛：HR 模块显式授权（查看者/操作员/管理员）、联系方式按职责脱敏、不可由普通成员改写的操作审计事件。未授权成员无法进入 HR 模块，越权与拒绝访问被记录，所有敏感操作可按对象、操作者、时间追溯。

## 范围

### 范围内

- `HrAccess` 授权模型：`(workspace_id, user_id)` 唯一，角色 `VIEWER` / `OPERATOR` / `ADMIN`。
- 权限执行：HR 模块入口要求 HR 授权；接口按角色分级；原「工作区成员/管理员」退化为授权授予来源（管理员授予 HR 权限）。
- 联系方式脱敏：`VIEWER` 角色在列表与详情中手机号、邮箱脱敏；`OPERATOR` / `ADMIN` 明文。
- `HrAuditLog` 审计事件表：不可被普通成员改写；覆盖敏感操作与越权拒绝。
- 审计查询：管理员可按对象、操作者、动作、时间范围查询。
- 前端：HR 模块成员授权管理页；审计记录查看页（管理员）。

### 不在范围内

- 字段级加密存储与密钥管理（仅脱敏与访问控制）。
- 简历下载短时授权 URL 与对象存储私有化（A4）。
- 面试官独立角色与职位级数据范围（面试官仍是文本字段）。
- 日志、异常上报、监控标签的脱敏治理（记录为已知限制）。

## 数据模型

### HrAccess

| 字段 | 类型 | 规则 |
|---|---|---|
| `id` | UUID | 主键。 |
| `workspace_id` | CharField(64) | 与 `user_id` 唯一约束。 |
| `user_id` | UUIDField | 授权用户。 |
| `role` | CharField(16) | `VIEWER` / `OPERATOR` / `ADMIN`。 |

- 角色能力：`VIEWER` 只读（列表/详情脱敏，无简历下载、无新建/编辑/流转）；`OPERATOR` 建档、上传、关联、流转（明文）；`ADMIN` 全部 + 职位管理、归档/恢复、合并、授权管理与审计查询。
- 授权管理 API 仅 HR `ADMIN` 可调用；被授权用户必须是当前工作区成员（校验内核成员 API）。

### HrAuditLog

| 字段 | 类型 | 规则 |
|---|---|---|
| `id` | UUID | 主键。 |
| `workspace_id` | CharField(64) | 索引。 |
| `user_id` | UUIDField | 操作者。 |
| `action` | CharField(32) | `VIEW_DETAIL` / `CREATE` / `UPDATE` / `ARCHIVE` / `RESTORE` / `DELETE` / `JOB_CLOSE` / `JOB_REOPEN` / `ASSIGNMENT_TRANSITION` / `RESUME_UPLOAD` / `RESUME_DOWNLOAD` / `RESUME_DELETE` / `MERGE` / `GRANT_ACCESS` / `REVOKE_ACCESS` / `EXPORT` / `ACCESS_DENIED`。 |
| `object_type` | CharField(32) | `CANDIDATE` / `JOB` / `ASSIGNMENT` / `RESUME` / `HR_ACCESS` / `OTHER`。 |
| `object_id` | CharField(64, blank) | 对象 ID 或描述。 |
| `result` | CharField(8) | `SUCCESS` / `FAILED` / `DENIED`。 |
| `detail` | TextField(blank) | 简短补充（原因、来源 IP 等）。 |
| `create_time` | DateTimeField(auto_now_add) | 索引。 |

- 写入方式：服务层关键操作显式调用审计 helper；列表接口不审计（防噪音），详情查看 `VIEW_DETAIL` 审计；`ACCESS_DENIED` 记录越权/未授权访问。
- 审计行只增不改；不提供普通成员的删除/修改 API。

## 权限与脱敏

### 权限执行

- HR 视图装饰器替换：`@hr_access_required`（任意 HR 角色）与 `@hr_admin_required`（ADMIN），替代既有 `@member_required` / `@manage_required` 在 HR 模块内的使用。
- 未获 HR 授权的工作区成员访问 HR 接口 → 403，并写 `ACCESS_DENIED` 审计。
- 角色能力矩阵：

| 能力 | VIEWER | OPERATOR | ADMIN |
|---|---|---|---|
| 候选人/职位/关联列表与详情（脱敏/明文） | 只读脱敏 | 明文 | 明文 |
| 简历下载 | 否 | 是 | 是 |
| 新建候选人、上传简历、关联职位、状态流转 | 否 | 是 | 是 |
| 职位创建/编辑/关闭/恢复、归档/恢复候选人、合并 | 否 | 否 | 是 |
| HR 授权管理与审计查询 | 否 | 否 | 是 |

### 脱敏规则

- 手机号：`138****5678`（前 3 后 4）。
- 邮箱：`ab***@example.com`（@ 前保留前 2 字符，后跟 `***`；域名保留）。
- `VIEWER` 在列表与详情均脱敏；空值保持空值。
- 序列化器按角色决定是否脱敏（`_masked_*` 输出）。

## API

统一前缀：`/admin/api/workspace/{workspace_id}/hr`。

| 方法 | 路径 | 用途 | 权限 |
|---|---|---|---|
| GET | `/access` | HR 授权成员列表（含角色） | ADMIN |
| PUT | `/access` | 批量设置成员角色（增/改/撤） | ADMIN |
| GET | `/audit-logs` | 审计查询（user_id / action / object_type / 时间范围 / 分页） | ADMIN |

- `PUT /access` 请求体：`{"items": [{"user_id": "...", "role": "OPERATOR"}]}`；`role` 非法 400；目标用户不在工作区 400；撤销用 `role: null` 或从列表移除语义（明确为 `{"user_id": "...", "role": null}` 撤销）。
- 审计查询支持 `user_id`、`action`、`object_type`、`start_time`、`end_time` 过滤与分页；非法枚举 400。
- 既有对象接口权限从「成员/管理员」迁移到 HR 角色（行为回归由测试保障）。

## 前端

- 新增「人事成员」页（仅 ADMIN 可见）：成员列表 + 角色下拉设置/撤销。
- 新增「审计日志」页（仅 ADMIN 可见）：筛选（用户/动作/对象类型/时间）+ 表格展示。
- 候选人/职位页面按角色渲染：VIEWER 隐藏新建/编辑/上传/流转按钮，联系方式显示脱敏。

## 测试

- 授权：未授权成员访问 HR 接口 403 且写审计；`PUT /access` 授予/撤销/非法角色/非成员 400。
- 脱敏：VIEWER 列表与详情手机/邮箱脱敏；OPERATOR/ADMIN 明文；空值保持。
- 审计：详情查看、创建、流转、关闭职位、上传/下载简历、合并、授权变更、越权拒绝均产生记录；查询过滤与分页正确；普通成员无审计查询权限。
- 回归：既有 hr 测试改用 HR 授权构造后全部通过（TEST 用户默认授予 OPERATOR 或按用例 ADMIN）。

## 验收

HR 全量测试 PASS、`manage.py check` 无问题、`makemigrations --check --dry-run` 无漂移、前端 `vue-tsc` 与 admin/chat 双构建 PASS。

## 取舍

- 授权基于 `(workspace_id, user_id)` 独立表而非改造内核成员模型：不侵入内核，撤回/升级即时生效。
- 审计在服务层显式埋点而非 DB 触发器：可携带业务上下文（原因、结果），实现成本可控；列表读不审计防噪音。
- 脱敏在序列化层而非存储层：本期不做字段级加密（存储加密依赖部署环境，见 A4/A5）。
- 日志/监控脱敏治理不在本期：记录为已知限制，A5 部署验证时人工检查。
