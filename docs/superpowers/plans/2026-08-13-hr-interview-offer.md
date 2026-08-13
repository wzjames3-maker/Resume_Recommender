# 面试与 Offer 流转实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 扩展 `apps/hr` 指派状态机（INTERVIEWING/OFFER/HIRED）并新增面试记录模型与 API，前端支持面试安排与结果反馈。

**架构：** 更新 `AssignmentStatus` 枚举与唯一约束；新增 `Interview` 模型；`RecruitmentService` 增加状态机合法流转校验与面试服务；职位展开区接入面试抽屉。

**技术栈：** Python 3.11、Django 5.2、DRF、PostgreSQL、Vue 3、Element Plus。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `apps/hr/models/recruitment.py` | 状态枚举扩展、唯一约束更新、`Interview` 模型。 |
| `apps/hr/migrations/0005_interview_and_status.py` | 状态约束更新与 `Interview` 表迁移。 |
| `apps/hr/serializers/recruitment.py` | 状态机校验、HIRED 再指派限制、面试服务。 |
| `apps/hr/views/recruitment.py` | 面试视图。 |
| `apps/hr/urls.py` | 面试路由。 |
| `apps/hr/tests.py` | 状态机、面试、HIRED 限制与隔离测试。 |
| `ui/src/api/type/hr.ts` | 状态联合类型扩展、`Interview` 类型。 |
| `ui/src/api/hr/recruitment.ts` | 面试 API 客户端。 |
| `ui/src/views/hr/jobs/index.vue` | 状态下拉扩展、面试抽屉、HIRED 提示。 |

### 任务 1：状态枚举扩展、Interview 模型与迁移

**文件：**
- 修改：`apps/hr/models/recruitment.py`
- 创建：`apps/hr/migrations/0005_interview_and_status.py`
- 测试：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的状态机与约束测试**

在 `apps/hr/tests.py` 追加：

```python
class InterviewStatusMachineTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]

    def _transition(self, to_status):
        return self.service.update_assignment(self.assignment_id, {"status": to_status})

    def test_full_offer_chain_is_legal(self):
        self._transition(AssignmentStatus.SCREEN_PASSED)
        self._transition(AssignmentStatus.INTERVIEWING)
        self._transition(AssignmentStatus.OFFER)
        self._transition(AssignmentStatus.HIRED)
        assignment = CandidateAssignment.objects.get(id=self.assignment_id)
        self.assertEqual(assignment.status, "HIRED")

    def test_illegal_transition_rejected(self):
        with self.assertRaisesRegex(AppApiException, "transition"):
            self._transition(AssignmentStatus.OFFER)

    def test_terminal_state_cannot_transition(self):
        self._transition(AssignmentStatus.REJECTED)
        with self.assertRaisesRegex(AppApiException, "transition"):
            self._transition(AssignmentStatus.SCREEN_PASSED)

    def test_hired_candidate_cannot_get_new_assignment(self):
        self._transition(AssignmentStatus.SCREEN_PASSED)
        self._transition(AssignmentStatus.INTERVIEWING)
        self._transition(AssignmentStatus.OFFER)
        self._transition(AssignmentStatus.HIRED)
        with self.assertRaisesRegex(AppApiException, "hired"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})

    def test_closed_job_cannot_enter_interviewing(self):
        self.service.edit_job(self.job.id, {"status": "CLOSED"})
        with self.assertRaisesRegex(AppApiException, "closed"):
            self._transition(AssignmentStatus.INTERVIEWING)
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.InterviewStatusMachineTests --keepdb
```

预期：FAIL（新状态与校验未实现）。

- [ ] **步骤 3：扩展枚举、约束与 Interview 模型**

`apps/hr/models/recruitment.py`：

- `AssignmentStatus` 增加 `INTERVIEWING`、`OFFER`、`HIRED`。
- 有效状态常量改为集合，唯一约束条件更新：

```python
ACTIVE_ASSIGNMENT_STATUSES = [
    AssignmentStatus.PENDING_SCREEN,
    AssignmentStatus.SCREEN_PASSED,
    AssignmentStatus.INTERVIEWING,
    AssignmentStatus.OFFER,
]

class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["workspace_id", "candidate", "job"],
            condition=Q(status__in=ACTIVE_ASSIGNMENT_STATUSES),
            name="hr_one_active_assignment_per_candidate_job",
        )
    ]
```

新增 `Interview`：

```python
class InterviewStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PASSED = "PASSED", "Passed"
    FAILED = "FAILED", "Failed"
    NO_SHOW = "NO_SHOW", "No show"
    CANCELLED = "CANCELLED", "Cancelled"


class Interview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    assignment = models.ForeignKey(CandidateAssignment, on_delete=models.CASCADE)
    round_no = models.PositiveSmallIntegerField()
    interviewer = models.CharField(max_length=64, blank=True, default="")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=InterviewStatus.choices, default=InterviewStatus.PENDING)
    feedback = models.TextField(blank=True, default="")
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_interview"
```

在 `models/__init__.py` 导出 `Interview`、`InterviewStatus`。

- [ ] **步骤 4：生成迁移并运行测试**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py makemigrations hr
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.InterviewStatusMachineTests --keepdb
```

预期：生成 `0005_interview_and_status.py`；5 个测试 PASS。

- [ ] **步骤 5：提交**

```bash
git add apps/hr/models apps/hr/migrations apps/hr/tests.py
git commit -m "feat(人事): 扩展指派状态机并新增面试模型"
```

### 任务 2：状态机校验、HIRED 限制与面试服务

**文件：**
- 修改：`apps/hr/serializers/recruitment.py`
- 修改：`apps/hr/views/recruitment.py`
- 修改：`apps/hr/urls.py`
- 测试：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的面试测试**

在 `apps/hr/tests.py` 追加：

```python
class InterviewServiceTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
        self.candidate = Candidate.objects.create(name="Bob", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]

    def test_create_interview_auto_increments_round(self):
        first = self.service.create_interview(self.assignment_id, {"interviewer": "张伟"})
        self.assertEqual(first["round_no"], 1)
        second = self.service.create_interview(self.assignment_id, {"interviewer": "李娜"})
        self.assertEqual(second["round_no"], 2)

    def test_update_interview_result_and_feedback(self):
        interview = self.service.create_interview(self.assignment_id, {})
        updated = self.service.update_interview(interview["id"], {"status": "PASSED", "feedback": "表现优秀"})
        self.assertEqual(updated["status"], "PASSED")
        self.assertEqual(updated["feedback"], "表现优秀")

    def test_interview_cross_workspace_not_found(self):
        foreign = Interview.objects.create(
            workspace_id="workspace-b", assignment_id=self.assignment_id, round_no=1,
        )
        with self.assertRaises(NotFound404):
            self.service.update_interview(foreign.id, {"status": "PASSED"})
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.InterviewServiceTests --keepdb
```

预期：FAIL（`create_interview` 未定义）。

- [ ] **步骤 3：实现服务、校验与视图**

`apps/hr/serializers/recruitment.py`：

- 定义流转表：

```python
_ALLOWED_TRANSITIONS = {
    AssignmentStatus.PENDING_SCREEN: {AssignmentStatus.SCREEN_PASSED, AssignmentStatus.REJECTED, AssignmentStatus.CLOSED},
    AssignmentStatus.SCREEN_PASSED: {AssignmentStatus.INTERVIEWING, AssignmentStatus.REJECTED, AssignmentStatus.CLOSED},
    AssignmentStatus.INTERVIEWING: {AssignmentStatus.OFFER, AssignmentStatus.REJECTED, AssignmentStatus.CLOSED},
    AssignmentStatus.OFFER: {AssignmentStatus.HIRED, AssignmentStatus.REJECTED, AssignmentStatus.CLOSED},
}
```

- `update_assignment` 的 `status` 分支：目标为有效状态（含 INTERVIEWING/OFFER）时复用现有候选人在库与职位开放校验；对 `HIRED`/`REJECTED`/`CLOSED` 不校验职位；校验合法流转，非法抛 `AppApiException(400, "Illegal status transition from X to Y")`。
- `create_assignment` 增加 HIRED 检查：

```python
if CandidateAssignment.objects.filter(
    workspace_id=self.workspace_id,
    candidate=candidate,
    status=AssignmentStatus.HIRED,
).exists():
    raise AppApiException(400, "Candidate is already hired")
```

- 面试服务：

```python
def create_interview(self, assignment_id, data):
    assignment = self._assignment(assignment_id)
    next_round = Interview.objects.filter(
        workspace_id=self.workspace_id, assignment=assignment
    ).aggregate(max=Max("round_no"))["max"] or 0
    interview = Interview.objects.create(
        workspace_id=self.workspace_id,
        assignment=assignment,
        round_no=int(data.get("round_no", next_round + 1)),
        interviewer=self._optional_string(data, "interviewer", 64),
        scheduled_at=data.get("scheduled_at") or None,
        user_id=self.user_id,
    )
    return self._interview_output(interview)

def list_interviews(self, assignment_id):
    assignment = self._assignment(assignment_id)
    interviews = Interview.objects.filter(workspace_id=self.workspace_id, assignment=assignment).order_by("round_no")
    return [self._interview_output(interview) for interview in interviews]

def update_interview(self, interview_id, data):
    interview = Interview.objects.filter(id=interview_id, workspace_id=self.workspace_id).first()
    if interview is None:
        raise NotFound404(404, "Resource not found")
    if "status" in data:
        if data["status"] not in InterviewStatus.values:
            raise AppApiException(400, "status is invalid")
        interview.status = data["status"]
    if "feedback" in data:
        interview.feedback = self._optional_string(data, "feedback", 4096)
    if "interviewer" in data:
        interview.interviewer = self._optional_string(data, "interviewer", 64)
    if "scheduled_at" in data:
        interview.scheduled_at = data["scheduled_at"] or None
    interview.save()
    return self._interview_output(interview)
```

需要 `from django.db.models import Max` 与 `Interview`、`InterviewStatus` 导入。`_assignment` 私有方法若已被一期删除（`update_assignment` 改为内联查询），需恢复一个用于只读查询的私有方法。

`apps/hr/views/recruitment.py` 追加：

```python
class InterviewAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def post(self, request, workspace_id, assignment_id):
        return result.success(_service(request, workspace_id).create_interview(assignment_id, request.data))

    @member_required
    def get(self, request, workspace_id, assignment_id):
        return result.success(_service(request, workspace_id).list_interviews(assignment_id))


class InterviewDetailAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def put(self, request, workspace_id, interview_id):
        return result.success(_service(request, workspace_id).update_interview(interview_id, request.data))
```

注册路由：

```python
path("workspace/<str:workspace_id>/hr/assignments/<str:assignment_id>/interviews", views.InterviewAPI.as_view()),
path("workspace/<str:workspace_id>/hr/interviews/<str:interview_id>", views.InterviewDetailAPI.as_view()),
```

在 `views/__init__.py` 导出新视图。

- [ ] **步骤 4：运行 HR 测试与 Django 检查**

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

预期：全部 PASS、检查无问题、迁移无变更。

- [ ] **步骤 5：提交**

```bash
git add apps/hr
git commit -m "feat(人事): 提供状态流转与面试管理 API"
```

### 任务 3：前端状态流转与面试抽屉

**文件：**
- 修改：`ui/src/api/type/hr.ts`
- 修改：`ui/src/api/hr/recruitment.ts`
- 修改：`ui/src/views/hr/jobs/index.vue`

- [ ] **步骤 1：扩展类型与 API 客户端**

`ui/src/api/type/hr.ts`：

```typescript
export type AssignmentStatus = 'PENDING_SCREEN' | 'SCREEN_PASSED' | 'INTERVIEWING' | 'OFFER' | 'HIRED' | 'REJECTED' | 'CLOSED'
export type InterviewStatus = 'PENDING' | 'PASSED' | 'FAILED' | 'NO_SHOW' | 'CANCELLED'

export interface Interview {
  id: string
  assignment_id: string
  round_no: number
  interviewer: string
  scheduled_at: string | null
  status: InterviewStatus
  feedback: string
  create_time: string
  update_time: string
}
```

`ui/src/api/hr/recruitment.ts`：

```typescript
const createInterview = (assignmentId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/assignments/${assignmentId}/interviews`, data) as Promise<Result<Interview>>

const getInterviews = (assignmentId: string) =>
  get(`${prefix.value}/assignments/${assignmentId}/interviews`) as Promise<Result<Interview[]>>

const updateInterview = (interviewId: string, data: Partial<Interview>) =>
  put(`${prefix.value}/interviews/${interviewId}`, data) as Promise<Result<Interview>>
```

- [ ] **步骤 2：职位展开区状态与面试 UI**

职位「候选人」标签页：

- 指派状态下拉选项扩展：待筛选、筛选通过、面试中、Offer 中、已入职、已淘汰、已关闭。
- 候选人行增加「面试」按钮，打开面试抽屉：
  - 展示 `getInterviews` 列表（轮次、面试官、时间、结果、反馈）。
  - 「安排面试」按钮与表单（面试官、面试时间），调用 `createInterview`。
  - 每条记录结果下拉与反馈编辑，调用 `updateInterview`。
- 匹配候选人区域：候选人已有 `HIRED` 指派时，「加入职位」按钮禁用并提示「候选人已入职」。

- [ ] **步骤 3：类型检查与双构建**

运行：

```bash
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat
```

预期：类型检查与两套构建退出码均为 0。

- [ ] **步骤 4：提交**

```bash
git add ui/src/api/hr ui/src/api/type/hr.ts ui/src/views/hr
git commit -m "feat(人事): 新增面试管理与状态流转页面"
```

### 任务 4：端到端验收与审计记录

**文件：**
- 修改：`README-hr.md`
- 修改：`docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md`

- [ ] **步骤 1：完整后端回归**

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

预期：全部测试 PASS、检查无问题、迁移无变更。

- [ ] **步骤 2：前端检查与产物扫描**

运行：

```bash
cd ui && node scripts/check-local-core-surface.mjs
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat
! rg -n '/(workflow|mcp_tools|text_to_speech|speech_to_text|play_demo_text)' ui/dist/admin ui/dist/chat
```

预期：表面检查与两套构建 PASS，扫描无匹配。

- [ ] **步骤 3：记录验收**

在 `README-hr.md` 与审计文档追加「人事四期验收」：状态机、面试、HIRED 限制、前端结果。

- [ ] **步骤 4：提交验收记录**

```bash
git add README-hr.md docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md
git commit -m "test(人事): 记录面试与 Offer 流转验收"
```

## 自检结果

- 规格覆盖：状态机、有效状态约束、Interview 模型、HIRED 限制、面试 API 与前端均有对应任务。
- 占位符：计划未使用待定实现或未定义步骤。
- 类型一致性：`Interview`、`InterviewStatus`、`create_interview`、`update_interview` 在所有任务中名称一致。
