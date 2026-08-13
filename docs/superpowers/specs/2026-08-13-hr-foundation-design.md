# 人事招聘基础闭环设计

## 目标

在精简 MaxKB 内核中新增 `apps/hr`，交付候选人、职位和候选人指派的最小招聘工作台。设计以当前 Django/DRF/Vue 架构为准，参考旧 AgentKB 的领域命名，但不迁移旧运行时实现。

## 架构

```text
Vue 管理端
  /hr/candidates                候选人列表与编辑
  /hr/jobs                      职位列表、详情与指派
       |
       v
/admin/api/workspace/{workspace_id}/hr/
       |
       v
apps/hr
  models -> serializers -> views -> urls
       |
       v
PostgreSQL（workspace_id 行级过滤）
```

在 `apps/maxkb/settings/base/web.py` 注册 `hr.apps.HrConfig`，在 `apps/maxkb/urls/web.py` 的管理 API 前缀下 include `hr.urls`。不注册 Celery 任务，不依赖知识库、Embedding 或 LLM。

## 数据模型

### Candidate

- UUID 主键和 `workspace_id`。
- `name` 必填，最大 128 字符。
- `email`、`phone`、`current_city`、`target_city`、`highest_degree`、`source` 可选短文本。
- `years_experience` 为非负整数，可为空。
- `skills` 为 JSON 字符串数组，默认为空数组。
- `note` 为可选长文本。
- `status` 仅接受 `ACTIVE`、`ARCHIVED`，默认 `ACTIVE`。
- `create_time`、`update_time` 与创建人 `user_id`。

### Job

- UUID 主键和 `workspace_id`。
- `name`、`department`、`city`、`level`、`headcount`、`description`。
- `headcount` 为 1 至 999 的整数。
- `status` 仅接受 `OPEN`、`CLOSED`，默认 `OPEN`。
- `create_time`、`update_time` 与创建人 `user_id`。

### CandidateAssignment

- UUID 主键和 `workspace_id`。
- 指向 `Candidate` 与 `Job` 的外键；两者须属于该 `workspace_id`。
- `status` 仅接受 `PENDING_SCREEN`、`SCREEN_PASSED`、`REJECTED`、`CLOSED`，默认 `PENDING_SCREEN`。
- `note`、`create_time`、`update_time` 与创建人 `user_id`。
- PostgreSQL 条件唯一约束：同一 `(workspace_id, candidate_id, job_id)` 最多一条状态为 `PENDING_SCREEN` 或 `SCREEN_PASSED` 的记录。

归档候选人前服务端检查不存在有效指派。职位关闭时不改写历史指派，但建立指派前服务端要求职位为 `OPEN`、候选人为 `ACTIVE`。

## API

统一前缀：`/admin/api/workspace/{workspace_id}/hr`。响应使用 `common.result.success`，认证使用 `TokenAuth`，视图使用现有 `APIView` 模式。

| 方法 | 路径 | 用途 | 最低权限 |
|---|---|---|---|
| GET | `/candidates/{page}/{page_size}` | 分页列出候选人，支持 `name`、`city`、`status` | 成员 |
| POST | `/candidates` | 新建候选人 | 成员 |
| GET | `/candidates/{candidate_id}` | 候选人详情与指派历史 | 成员 |
| PUT | `/candidates/{candidate_id}` | 编辑候选人 | 工作区管理员 |
| PUT | `/candidates/{candidate_id}/archive` | 归档候选人 | 工作区管理员 |
| GET | `/jobs/{page}/{page_size}` | 分页列出职位 | 成员 |
| POST | `/jobs` | 新建职位 | 工作区管理员 |
| GET | `/jobs/{job_id}` | 职位详情与指派列表 | 成员 |
| PUT | `/jobs/{job_id}` | 编辑职位或关闭职位 | 工作区管理员 |
| POST | `/jobs/{job_id}/assignments` | 创建候选人指派 | 成员 |
| PUT | `/assignments/{assignment_id}` | 更新指派状态或备注 | 成员；管理员可操作任意记录 |

列表、详情和变更操作均将资源查询限制为 URL 的 `workspace_id`。找不到资源或资源不属于当前工作区时统一返回 404。序列化器负责字段范围、状态值和业务规则；视图不直接写 ORM。

一期不引入新的权限常量。成员接口使用既有 `RoleConstants.USER` 与 `RoleConstants.WORKSPACE_MANAGE`；管理员写接口额外在序列化器中调用 `is_workspace_manage`。

## 前端

新增 `ui/src/router/modules/hr.ts`，放入工作区导航，顺序在知识库和应用之后。路由为：

- `/hr/candidates`：候选人列表，包含筛选、分页、新建、编辑、归档和加入职位。
- `/hr/jobs`：职位列表，包含新建、编辑、关闭和查看关联候选人。
- `/hr/jobs/:id`：职位详情与指派表格，支持更新筛选状态。

复用现有 `LayoutContainer`、Element Plus `el-table`、`el-dialog`、分页器、请求封装和当前工作区 store。HR API client 从用户工作区 ID 动态构造前缀，遵循知识库 API 的模式。

## 测试

后端测试至少覆盖：

- 有效候选人、职位和指派的创建。
- 已关闭职位与已归档候选人不能创建指派。
- 重复有效指派被拒绝，终态后可重新创建。
- 有效指派存在时不能归档候选人。
- 资源属于其他工作区时，详情、编辑和指派均按不存在处理。
- 非工作区管理员不能编辑/归档候选人或创建/关闭职位。

验收命令：

```bash
MAXKB_CONFIG_TYPE=ENV ... uv run python apps/manage.py test hr.tests --keepdb
MAXKB_CONFIG_TYPE=ENV ... uv run python apps/manage.py check
MAXKB_CONFIG_TYPE=ENV ... uv run python apps/manage.py makemigrations --check --dry-run
cd ui && pnpm exec vue-tsc --build
cd ui && pnpm exec vite build && pnpm exec vite build --mode chat
```

## 取舍

- 采用归档替代删除，避免早期实现破坏指派历史。
- 部门以职位文本字段承载，部门树属于后续组织模块。
- 指派状态只覆盖筛选阶段；面试和 Offer 迁移前不预留虚假状态。
- 旧 AgentKB 的领域规则用于测试灵感，但不得复制其 FastAPI、SQLAlchemy 或独立用户表。
