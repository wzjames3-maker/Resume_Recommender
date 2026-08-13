# 人事招聘基础闭环实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在精简 MaxKB 内核中实现按工作区隔离的候选人、职位和候选人指派基础闭环。

**架构：** 新增 `apps/hr` Django app，模型按 `workspace_id` 隔离，序列化器集中字段和业务校验，DRF 视图复用 MaxKB 的 Token 认证和结果包装。管理端新增人事部路由，复用 Element Plus 表格与对话框完成候选人、职位和指派操作。

**技术栈：** Python 3.11、Django 5.2、Django REST Framework、PostgreSQL、Vue 3、TypeScript、Element Plus、pnpm。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `apps/hr/apps.py` | 注册人事 Django app。 |
| `apps/hr/models/recruitment.py` | Candidate、Job、CandidateAssignment 模型、状态枚举和有效指派唯一约束。 |
| `apps/hr/models/__init__.py` | 导出 HR 模型。 |
| `apps/hr/migrations/0001_initial.py` | 创建 HR 域表与数据库约束。 |
| `apps/hr/serializers/recruitment.py` | 资源查询、字段校验、权限与领域规则。 |
| `apps/hr/views/recruitment.py` | 候选人、职位、指派 API 视图。 |
| `apps/hr/urls.py` | 注册 HR 管理端 API 路由。 |
| `apps/hr/tests.py` | 模型、序列化器与 API 级工作区隔离回归测试。 |
| `apps/maxkb/settings/base/web.py` | 将 `hr.apps.HrConfig` 加入 `INSTALLED_APPS`。 |
| `apps/maxkb/urls/web.py` | 在管理端 API 前缀 include `hr.urls`。 |
| `ui/src/api/hr/recruitment.ts` | 以当前工作区 ID 构造候选人、职位和指派请求。 |
| `ui/src/api/type/hr.ts` | HR 前端数据类型。 |
| `ui/src/router/modules/hr.ts` | 人事部菜单和候选人/职位路由。 |
| `ui/src/views/hr/candidates/index.vue` | 候选人表格、筛选、编辑和加入职位。 |
| `ui/src/views/hr/jobs/index.vue` | 职位表格、编辑、关闭与关联候选人列表。 |

### 任务 1：建立 HR app、模型和迁移

**文件：**
- 创建：`apps/hr/__init__.py`
- 创建：`apps/hr/apps.py`
- 创建：`apps/hr/models/__init__.py`
- 创建：`apps/hr/models/recruitment.py`
- 创建：`apps/hr/migrations/__init__.py`
- 创建：`apps/hr/migrations/0001_initial.py`
- 修改：`apps/maxkb/settings/base/web.py`
- 测试：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的模型约束测试**

```python
from django.db import IntegrityError, transaction
from django.test import TestCase

from hr.models import AssignmentStatus, Candidate, CandidateAssignment, Job


class AssignmentConstraintTests(TestCase):
    def setUp(self):
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Python Engineer", department="Engineering", headcount=1,
                                      workspace_id="workspace-a")

    def test_only_one_active_assignment_per_candidate_and_job(self):
        CandidateAssignment.objects.create(candidate=self.candidate, job=self.job, workspace_id="workspace-a")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CandidateAssignment.objects.create(candidate=self.candidate, job=self.job, workspace_id="workspace-a")

    def test_terminal_assignment_allows_a_new_assignment(self):
        CandidateAssignment.objects.create(candidate=self.candidate, job=self.job, workspace_id="workspace-a",
                                           status=AssignmentStatus.REJECTED)
        assignment = CandidateAssignment.objects.create(candidate=self.candidate, job=self.job,
                                                        workspace_id="workspace-a")
        self.assertEqual(assignment.status, AssignmentStatus.PENDING_SCREEN)
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.AssignmentConstraintTests --keepdb
```

预期：FAIL，提示 `No module named 'hr'`。

- [ ] **步骤 3：实现模型与 app 注册**

创建 `apps/hr/apps.py`：

```python
from django.apps import AppConfig


class HrConfig(AppConfig):
    name = "hr"
    verbose_name = "人事部"
```

在 `apps/hr/models/recruitment.py` 定义：

```python
import uuid_utils.compat as uuid
from django.db import models
from django.db.models import Q


class CandidateStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class JobStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"


class AssignmentStatus(models.TextChoices):
    PENDING_SCREEN = "PENDING_SCREEN", "Pending screen"
    SCREEN_PASSED = "SCREEN_PASSED", "Screen passed"
    REJECTED = "REJECTED", "Rejected"
    CLOSED = "CLOSED", "Closed"


class Candidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=128, db_index=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, default="")
    current_city = models.CharField(max_length=64, blank=True, default="")
    target_city = models.CharField(max_length=64, blank=True, default="")
    highest_degree = models.CharField(max_length=32, blank=True, default="")
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    skills = models.JSONField(default=list)
    source = models.CharField(max_length=64, blank=True, default="")
    note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=CandidateStatus.choices, default=CandidateStatus.ACTIVE)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=128, db_index=True)
    department = models.CharField(max_length=128, blank=True, default="")
    city = models.CharField(max_length=64, blank=True, default="")
    level = models.CharField(max_length=64, blank=True, default="")
    headcount = models.PositiveSmallIntegerField(default=1)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=JobStatus.choices, default=JobStatus.OPEN)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)


class CandidateAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.PROTECT)
    job = models.ForeignKey(Job, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=AssignmentStatus.choices,
                              default=AssignmentStatus.PENDING_SCREEN)
    note = models.TextField(blank=True, default="")
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "candidate", "job"],
                condition=Q(status__in=[AssignmentStatus.PENDING_SCREEN, AssignmentStatus.SCREEN_PASSED]),
                name="hr_one_active_assignment_per_candidate_job",
            )
        ]
```

使用项目的 `uuid_utils.compat.uuid.uuid7` 作为 UUID 默认值，使用 `auto_now_add=True` 与 `auto_now=True` 记录时间。将 `HrConfig` 加入 `INSTALLED_APPS`，从 `models/__init__.py` 导出三个模型和两个状态枚举。

- [ ] **步骤 4：生成迁移并运行模型测试**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py makemigrations hr
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.AssignmentConstraintTests --keepdb
```

预期：生成 `0001_initial.py`；两个测试 PASS。

- [ ] **步骤 5：提交模型变更**

```bash
git add apps/hr apps/maxkb/settings/base/web.py
git commit -m "feat(人事): 新增招聘基础数据模型"
```

### 任务 2：实现领域服务、管理端 API 和回归测试

**文件：**
- 创建：`apps/hr/serializers/__init__.py`
- 创建：`apps/hr/serializers/recruitment.py`
- 创建：`apps/hr/views/__init__.py`
- 创建：`apps/hr/views/recruitment.py`
- 创建：`apps/hr/urls.py`
- 修改：`apps/maxkb/urls/web.py`
- 修改：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的领域规则测试**

在 `apps/hr/tests.py` 添加：

```python
from common.exception.app_exception import AppApiException, NotFound404
from hr.serializers.recruitment import RecruitmentService


class RecruitmentServiceTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(
            workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True
        )
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Python Engineer", department="Engineering", headcount=1,
                                      workspace_id="workspace-a")

    def test_closed_job_rejects_assignment(self):
        self.job.status = "CLOSED"
        self.job.save(update_fields=["status"])
        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})

    def test_archive_rejects_candidate_with_active_assignment(self):
        self.service.create_assignment(self.job.id, self.candidate.id, {})
        with self.assertRaisesRegex(AppApiException, "active assignment"):
            self.service.archive_candidate(self.candidate.id)

    def test_cross_workspace_resource_is_not_found(self):
        foreign = Candidate.objects.create(name="Bob", workspace_id="workspace-b")
        with self.assertRaises(NotFound404):
            self.service.get_candidate(foreign.id)
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.RecruitmentServiceTests --keepdb
```

预期：FAIL，提示 `RecruitmentService` 尚未定义。

- [ ] **步骤 3：实现服务与 API 视图**

`RecruitmentService` 接受 `workspace_id`、`user_id` 与 `is_workspace_manage`，每个查询从如下私有方法开始：

```python
def _candidate(self, candidate_id):
    candidate = Candidate.objects.filter(id=candidate_id, workspace_id=self.workspace_id).first()
    if candidate is None:
        raise NotFound404(404, "Resource not found")
    return candidate

def _require_manage(self):
    if not self.is_workspace_manage:
        raise AppUnauthorizedFailed(403, "Workspace administrator permission is required")
```

实现 `create_candidate`、`page_candidates`、`get_candidate`、`edit_candidate`、`archive_candidate`、`create_job`、`page_jobs`、`get_job`、`edit_job`、`create_assignment` 与 `update_assignment`。服务使用 `transaction.atomic()` 创建指派，并在捕获 `IntegrityError` 后抛出 `AppApiException(400, "An active assignment already exists")`。

`apps/hr/views/recruitment.py` 复用下列视图模式：

```python
class CandidateAPI(APIView):
    authentication_classes = [TokenAuth]

    def post(self, request, workspace_id):
        return result.success(_service(request, workspace_id).create_candidate(request.data))

    def get(self, request, workspace_id, current_page, page_size):
        return result.success(_service(request, workspace_id).page_candidates(current_page, page_size, request.query_params))
```

`_service()` 必须调用 `is_workspace_manage(request.user.id, workspace_id)`。在 `apps/hr/urls.py` 注册设计规格中列出的 11 个 API 操作，再在 `apps/maxkb/urls/web.py` 的 `homepage.urls` 之后 include `hr.urls`。

- [ ] **步骤 4：运行 HR 后端测试与 Django 检查**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests --keepdb
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py check
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py makemigrations --check --dry-run
```

预期：全部测试 PASS，system check 无问题，迁移无变更。

- [ ] **步骤 5：提交 API 变更**

```bash
git add apps/hr apps/maxkb/urls/web.py
git commit -m "feat(人事): 提供候选人职位与指派 API"
```

### 任务 3：实现人事部管理端

**文件：**
- 创建：`ui/src/api/type/hr.ts`
- 创建：`ui/src/api/hr/recruitment.ts`
- 创建：`ui/src/router/modules/hr.ts`
- 创建：`ui/src/views/hr/candidates/index.vue`
- 创建：`ui/src/views/hr/jobs/index.vue`

- [ ] **步骤 1：编写 HR API 类型和客户端**

创建 `ui/src/api/type/hr.ts`：

```typescript
export interface Candidate {
  id: string
  name: string
  current_city: string
  target_city: string
  years_experience: number | null
  skills: string[]
  status: 'ACTIVE' | 'ARCHIVED'
  update_time: string
}

export interface Job {
  id: string
  name: string
  department: string
  city: string
  headcount: number
  status: 'OPEN' | 'CLOSED'
  active_assignment_count: number
}
```

创建 `ui/src/api/hr/recruitment.ts`，按知识库 API 的动态前缀模式调用：

```typescript
const prefix = computedPrefix('/hr')

const getCandidates = (page: pageRequest, params?: Record<string, unknown>) =>
  get(`${prefix.value}/candidates/${page.current_page}/${page.page_size}`, params)

const createAssignment = (jobId: string, candidateId: string) =>
  post(`${prefix.value}/jobs/${jobId}/assignments`, { candidate_id: candidateId })
```

`computedPrefix` 不新增全局帮助函数；在此文件中以 `useStore().user.getWorkspaceId()` 直接实现，与 `knowledge.ts` 相同。

- [ ] **步骤 2：实现路由、候选人和职位页面**

`ui/src/router/modules/hr.ts`：

```typescript
import { RoleConst } from '@/utils/permission/data'

const hrRouter = {
  path: '/hr',
  name: 'hr',
  meta: {
    title: '人事部', menu: true,
    permission: [RoleConst.USER.getWorkspaceRole, RoleConst.WORKSPACE_MANAGE.getWorkspaceRole],
    icon: 'app-user', group: 'workspace', order: 5,
  },
  redirect: '/hr/candidates',
  component: () => import('@/layout/layout-template/SimpleLayout.vue'),
  children: [
    { path: '/hr/candidates', name: 'hr-candidates', meta: { title: '候选人', activeMenu: '/hr' }, component: () => import('@/views/hr/candidates/index.vue') },
    { path: '/hr/jobs', name: 'hr-jobs', meta: { title: '职位', activeMenu: '/hr' }, component: () => import('@/views/hr/jobs/index.vue') },
  ],
}

export default hrRouter
```

候选人页必须使用 `LayoutContainer`、`ContentContainer`、`el-table` 和 `el-pagination`；提供姓名/城市/状态过滤、创建编辑对话框、归档确认，以及打开“加入职位”对话框并选择 `OPEN` 职位。职位页必须显示有效指派数、提供创建编辑对话框、关闭确认，并在行展开区域显示关联候选人和所有成员均可使用的筛选状态更新控件。

- [ ] **步骤 3：运行类型检查确认前端通过**

运行：

```bash
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
```

预期：退出码为 0。

- [ ] **步骤 4：运行双端构建**

运行：

```bash
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat
```

预期：两个构建均退出码为 0。

- [ ] **步骤 5：提交前端变更**

```bash
git add ui/src/api/hr ui/src/api/type/hr.ts ui/src/router/modules/hr.ts ui/src/views/hr
git commit -m "feat(人事): 新增候选人与职位管理页面"
```

### 任务 4：完成端到端验收与审计记录

**文件：**
- 修改：`README-hr.md`
- 修改：`docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md`

- [ ] **步骤 1：运行完整 HR 回归**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py check
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py makemigrations --check --dry-run
```

预期：全部测试 PASS，检查无问题，迁移无变更。

- [ ] **步骤 2：复跑前端检查和产物扫描**

运行：

```bash
cd ui && node scripts/check-local-core-surface.mjs
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat
! rg -n '/(workflow|mcp_tools|text_to_speech|speech_to_text|play_demo_text)' ui/dist/admin ui/dist/chat
```

预期：表面检查和两套构建 PASS，扫描无匹配。

- [ ] **步骤 3：记录验收**

在 `README-hr.md` 新增“人事一期验收”章节，记录 HR API、迁移、后端测试、类型检查和两套构建的实际结果。同步在审计文档追加 HR 模块已新增且不重新引入已裁剪运行时能力的验收记录。

- [ ] **步骤 4：提交验收记录**

```bash
git add README-hr.md docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md
git commit -m "test(人事): 记录招聘基础闭环验收"
```

## 自检结果

- 规格覆盖：模型、约束、权限、API、管理端页面和验收均由任务 1 至 4 覆盖。
- 占位符：计划未使用待定实现或未定义的后续步骤。
- 类型一致性：`Candidate`、`Job`、`CandidateAssignment` 和 4 个指派状态在所有任务中使用相同名称。
