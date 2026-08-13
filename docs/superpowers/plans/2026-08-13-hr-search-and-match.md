# 候选人组合搜索与职位匹配实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 `apps/hr` 实现候选人高级组合搜索、职位技能要求与匹配建议，前端支持一键加入职位。

**架构：** `Job` 新增 `skill_requirements` JSON 数组；`page_candidates` 扩展组合过滤；新增职位匹配服务计算技能交集与城市加分；前端职位表单与展开区接入匹配结果。

**技术栈：** Python 3.11、Django 5.2、DRF、PostgreSQL JSONB、Vue 3、Element Plus。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `apps/hr/models/recruitment.py` | `Job` 增加 `skill_requirements` 字段。 |
| `apps/hr/migrations/0004_job_skill_requirements.py` | 新增字段迁移。 |
| `apps/hr/serializers/recruitment.py` | 高级搜索过滤、职位技能要求校验、职位匹配服务。 |
| `apps/hr/views/recruitment.py` | 职位匹配视图。 |
| `apps/hr/urls.py` | 匹配路由。 |
| `apps/hr/tests.py` | 搜索、匹配、校验与权限测试。 |
| `ui/src/api/type/hr.ts` | `Job` 增加 `skill_requirements`；新增匹配结果类型。 |
| `ui/src/api/hr/recruitment.ts` | 匹配接口。 |
| `ui/src/views/hr/jobs/index.vue` | 职位表单技能要求、匹配候选人展示与一键加入。 |
| `ui/src/views/hr/candidates/index.vue` | 学历、年限区间、多技能筛选。 |

### 任务 1：Job 技能要求字段与高级搜索

**文件：**
- 修改：`apps/hr/models/recruitment.py`
- 创建：`apps/hr/migrations/0004_job_skill_requirements.py`
- 修改：`apps/hr/serializers/recruitment.py`
- 测试：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的搜索测试**

在 `apps/hr/tests.py` 追加：

```python
class AdvancedSearchTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
        self.alice = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", skills=["Python", "Django"],
            highest_degree="本科", years_experience=5, source="JOB_SITE",
        )
        self.bob = Candidate.objects.create(
            name="Bob", workspace_id="workspace-a", skills=["Java", "Spring"],
            highest_degree="硕士", years_experience=3, source="REFERRAL",
        )

    def test_multi_skill_and_semantics(self):
        result = self.service.page_candidates(1, 20, {"skills": "Python,Django"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Alice")

    def test_degree_and_years_range_filter(self):
        result = self.service.page_candidates(1, 20, {"highest_degree": "硕士", "years_min": "2", "years_max": "4"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Bob")

    def test_source_filter(self):
        result = self.service.page_candidates(1, 20, {"source": "REFERRAL"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Bob")

    def test_years_range_excludes_null_experience(self):
        Candidate.objects.create(name="NullExp", workspace_id="workspace-a", skills=[], years_experience=None)
        result = self.service.page_candidates(1, 20, {"years_min": "1"})
        self.assertEqual(result["total"], 2)
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.AdvancedSearchTests --keepdb
```

预期：FAIL（当前 `page_candidates` 不支持这些过滤）。

- [ ] **步骤 3：实现 `skill_requirements` 字段与高级搜索**

在 `apps/hr/models/recruitment.py` 的 `Job` 增加：

```python
    skill_requirements = models.JSONField(default=list)
```

在 `apps/hr/serializers/recruitment.py` 的 `page_candidates` 追加过滤（沿用现有参数读取模式）：

```python
        highest_degree = query.get("highest_degree")
        years_min = query.get("years_min")
        years_max = query.get("years_max")
        if highest_degree:
            queryset = queryset.filter(highest_degree=highest_degree)
        if years_min:
            try:
                years_min = int(years_min)
            except (TypeError, ValueError) as exc:
                raise AppApiException(400, "years_min is invalid") from exc
            queryset = queryset.filter(years_experience__gte=years_min)
        if years_max:
            try:
                years_max = int(years_max)
            except (TypeError, ValueError) as exc:
                raise AppApiException(400, "years_max is invalid") from exc
            queryset = queryset.filter(years_experience__lte=years_max)
```

`skills` 过滤已在一期实现（AND 语义）。`create_job` 与 `edit_job` 增加 `skill_requirements` 处理：

```python
    @staticmethod
    def _skill_requirements(data):
        value = data.get("skill_requirements", [])
        if not isinstance(value, list) or any(not isinstance(skill, str) or not skill.strip() for skill in value):
            raise AppApiException(400, "skill_requirements must be a list of non-empty strings")
        return [skill.strip() for skill in value]
```

创建职位时 `skill_requirements=self._skill_requirements(data)`；编辑职位时同样处理并加入 `update_fields`。

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
uv run python apps/manage.py test hr.tests.AdvancedSearchTests --keepdb
```

预期：生成 `0004_job_skill_requirements.py`；4 个测试 PASS。

- [ ] **步骤 5：提交**

```bash
git add apps/hr/models apps/hr/migrations apps/hr/serializers apps/hr/tests.py
git commit -m "feat(人事): 扩展候选人组合搜索与职位技能要求"
```

### 任务 2：职位匹配服务与 API

**文件：**
- 修改：`apps/hr/serializers/recruitment.py`
- 修改：`apps/hr/views/recruitment.py`
- 修改：`apps/hr/urls.py`
- 测试：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的匹配测试**

在 `apps/hr/tests.py` 追加：

```python
class JobMatchTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
        self.alice = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", skills=["Python", "Django", "PostgreSQL"],
            current_city="杭州", target_city="上海", years_experience=5, status="ACTIVE",
        )
        self.bob = Candidate.objects.create(
            name="Bob", workspace_id="workspace-a", skills=["Java"], current_city="北京",
            target_city="杭州", years_experience=3, status="ACTIVE",
        )
        self.job = Job.objects.create(
            name="Python Engineer", department="Engineering", city="杭州", headcount=1,
            workspace_id="workspace-a", skill_requirements=["Python", "Django"],
        )

    def test_match_scores_skills_and_city(self):
        result = self.service.match_job_candidates(self.job.id, 1, 20)
        by_name = {item["name"]: item for item in result["records"]}
        self.assertEqual(by_name["Alice"]["match_score"], 10)
        self.assertEqual(by_name["Alice"]["matched_skills"], ["Python", "Django"])
        self.assertEqual(by_name["Bob"]["match_score"], 2)

    def test_match_sorted_by_score_desc(self):
        result = self.service.match_job_candidates(self.job.id, 1, 20)
        scores = [item["match_score"] for item in result["records"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_match_without_requirements_returns_empty(self):
        self.job.skill_requirements = []
        self.job.city = ""
        self.job.save(update_fields=["skill_requirements", "city"])
        result = self.service.match_job_candidates(self.job.id, 1, 20)
        self.assertEqual(result["total"], 0)

    def test_match_rejects_closed_job_and_cross_workspace(self):
        self.job.status = "CLOSED"
        self.job.save(update_fields=["status"])
        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.match_job_candidates(self.job.id, 1, 20)
        foreign = Job.objects.create(name="F", workspace_id="workspace-b", headcount=1, city="杭州",
                                     skill_requirements=["Python"])
        with self.assertRaises(NotFound404):
            self.service.match_job_candidates(foreign.id, 1, 20)
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.JobMatchTests --keepdb
```

预期：FAIL，提示 `match_job_candidates` 未定义。

- [ ] **步骤 3：实现匹配服务与视图**

在 `apps/hr/serializers/recruitment.py` 追加：

```python
    def match_job_candidates(self, job_id, current_page, page_size):
        job = self._job(job_id)
        if job.status != JobStatus.OPEN:
            raise AppApiException(400, "Job is closed")
        requirements = [skill.lower() for skill in job.skill_requirements]
        candidates = Candidate.objects.filter(workspace_id=self.workspace_id, status=CandidateStatus.ACTIVE)
        records = []
        for candidate in candidates:
            score = 0
            matched = []
            for skill in requirements:
                if any(s.lower() == skill for s in candidate.skills):
                    score += 2
                    matched.append(skill)
            if job.city:
                if candidate.current_city == job.city or candidate.target_city == job.city:
                    score += 2
            if score > 0:
                records.append({
                    "candidate_id": str(candidate.id),
                    "name": candidate.name,
                    "current_city": candidate.current_city,
                    "target_city": candidate.target_city,
                    "years_experience": candidate.years_experience,
                    "skills": candidate.skills,
                    "match_score": score,
                    "matched_skills": matched,
                })
        records.sort(key=lambda item: item["match_score"], reverse=True)
        total = len(records)
        start = (current_page - 1) * page_size
        return {"total": total, "records": records[start:start + page_size]}
```

在 `apps/hr/views/recruitment.py` 追加 `JobMatchAPI`：

```python
class JobMatchAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def get(self, request, workspace_id, job_id, current_page, page_size):
        return result.success(
            _service(request, workspace_id).match_job_candidates(job_id, current_page, page_size)
        )
```

注册到 `apps/hr/urls.py`：

```python
    path("workspace/<str:workspace_id>/hr/jobs/<str:job_id>/matches/<int:current_page>/<int:page_size>", views.JobMatchAPI.as_view()),
```

在 `apps/hr/views/__init__.py` 导出 `JobMatchAPI`。

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
git commit -m "feat(人事): 提供职位匹配建议 API"
```

### 任务 3：前端搜索增强与匹配展示

**文件：**
- 修改：`ui/src/api/type/hr.ts`
- 修改：`ui/src/api/hr/recruitment.ts`
- 修改：`ui/src/views/hr/jobs/index.vue`
- 修改：`ui/src/views/hr/candidates/index.vue`

- [ ] **步骤 1：扩展类型与 API 客户端**

`ui/src/api/type/hr.ts` 的 `Job` 增加：

```typescript
  skill_requirements: string[]
```

追加：

```typescript
export interface JobMatchCandidate {
  candidate_id: string
  name: string
  current_city: string
  target_city: string
  years_experience: number | null
  skills: string[]
  match_score: number
  matched_skills: string[]
}

export interface JobMatchPage {
  total: number
  records: JobMatchCandidate[]
}
```

`ui/src/api/hr/recruitment.ts` 追加：

```typescript
const getJobMatches = (jobId: string, page: pageRequest) =>
  get(`${prefix.value}/jobs/${jobId}/matches/${page.current_page}/${page.page_size}`) as Promise<Result<JobMatchPage>>
```

`Job` 创建/编辑时 `skill_requirements` 由逗号分隔文本转换。

- [ ] **步骤 2：职位页技能要求与匹配展示**

职位创建/编辑对话框增加「技能要求」输入（逗号分隔），保存时转换为数组。职位展开区在现有「候选人」标签旁增加「匹配候选人」区域：

- 调用 `getJobMatches`，展示匹配分数、命中技能与候选人姓名。
- 「加入职位」按钮调用 `createAssignment`，成功后刷新匹配列表与职位详情。

- [ ] **步骤 3：候选人页搜索增强**

候选人检索区增加：

- 最高学历下拉（博士/硕士/本科/大专/中专/高中）。
- 工作年限最小/最大 `el-input-number`。
- 技能输入已在二期加入（支持逗号分隔多值，AND 语义由后端保证）。

- [ ] **步骤 4：类型检查与双构建**

运行：

```bash
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build
cd ui && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat
```

预期：类型检查与两套构建退出码均为 0。

- [ ] **步骤 5：提交**

```bash
git add ui/src/api/hr ui/src/api/type/hr.ts ui/src/views/hr
git commit -m "feat(人事): 新增职位匹配与高级搜索页面"
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

在 `README-hr.md` 与审计文档追加「人事三期验收」：组合搜索、职位匹配、技能要求、前端展示与一键加入职位结果。

- [ ] **步骤 4：提交验收记录**

```bash
git add README-hr.md docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md
git commit -m "test(人事): 记录搜索与匹配验收"
```

## 自检结果

- 规格覆盖：技能要求字段、高级搜索、匹配服务、前端展示、一键加入职位与测试均有对应任务。
- 占位符：计划未使用待定实现或未定义步骤。
- 类型一致性：`skill_requirements`、`match_job_candidates`、`JobMatchCandidate` 在所有任务中名称一致。
