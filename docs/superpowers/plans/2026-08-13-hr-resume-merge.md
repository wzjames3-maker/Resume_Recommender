# HR 七期实现计划：简历下载/原文查看、候选人合并与重复检测

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 简历可下载原文件与查看提取文本；候选人列表标记疑似重复并在编辑时查重提示；支持候选人合并（主优先补充字段、关系迁移、有效指派冲突拒绝）。

**架构：** 服务方法（`download_resume`/`resume_content`/`check_duplicate`/`merge_candidates`/`page_candidates` 扩展）→ 薄视图（嵌套类 Download/Content/Merge + 独立 CheckDuplicate，复用既有装饰器）→ 前端候选人页（简历对话框、重复 tag、保存查重、合并对话框）。

**技术栈：** Django 5.2 / DRF、`FileResponse`、Vue 3.5 + Element Plus、axios blob（复用 `exportFile`）。

**规格：** `docs/superpowers/specs/2026-08-13-hr-resume-merge-design.md`

---

## 文件结构

- 修改 `apps/hr/serializers/recruitment.py`：`_resume_file`、`download_resume`、`resume_content`、`check_duplicate`、`merge_candidates`、`page_candidates` 扩展（任务 1、2、3）
- 修改 `apps/hr/views/recruitment.py`：`ResumeDetailAPI.Download` / `.Content`、`CandidateCheckDuplicateAPI`、`CandidateDetailAPI.Merge`（任务 1、2、3）
- 修改 `apps/hr/views/__init__.py`、`apps/hr/urls.py`（任务 1、2、3）
- 修改 `apps/hr/tests.py`：`ResumeDownloadTests`、`DuplicateDetectionTests`、`CandidateMergeTests`（任务 1、2、3）
- 修改 `ui/src/api/type/hr.ts`、`ui/src/api/hr/recruitment.ts`（任务 4）
- 修改 `ui/src/views/hr/candidates/index.vue`（任务 5）
- 修改 `README-hr.md`、`docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md`（任务 6）

**测试命令**（仓库根目录；env 前缀）：

```bash
export MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0
uv run python apps/manage.py test hr.tests --keepdb
```

**前端验证命令**（`ui/` 目录）：

```bash
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build >/dev/null 2>&1 && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat >/dev/null 2>&1
```

**基线**：hr.tests 单独 74 个测试；四 app 全量 86 个。

---

### 任务 1：简历下载与原文查看（TDD）

**文件：**
- 修改：`apps/hr/serializers/recruitment.py`
- 修改：`apps/hr/views/recruitment.py`、`apps/hr/views/__init__.py`、`apps/hr/urls.py`
- 修改：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的测试 `ResumeDownloadTests`**

在 `apps/hr/tests.py` 末尾追加：

```python
class ResumeDownloadTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
        self.handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        self.handle.write("姓名：张三\n电话：13812345678".encode("utf-8"))
        self.handle.close()
        self.resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="zhangsan.txt", extension="txt",
            file_path=self.handle.name, file_size=os.path.getsize(self.handle.name),
            sha256="sha-" + uuid.uuid7().hex, source_channel="OTHER", status="SUCCESS",
        )

    def test_download_returns_path_name_and_mime(self):
        file_path, file_name, content_type = self.service.download_resume(str(self.resume.id))
        self.assertEqual(file_path, self.handle.name)
        self.assertEqual(file_name, "zhangsan.txt")
        self.assertEqual(content_type, "text/plain")

    def test_download_missing_file_raises_404(self):
        self.resume.file_path = "/tmp/not-exists-" + uuid.uuid7().hex + ".txt"
        self.resume.save(update_fields=["file_path"])
        with self.assertRaises(NotFound404):
            self.service.download_resume(str(self.resume.id))

    def test_download_cross_workspace_raises_404(self):
        foreign = ResumeFile.objects.create(
            workspace_id="workspace-b", file_name="f.txt", extension="txt",
            file_path="/tmp/f.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
        )
        with self.assertRaises(NotFound404):
            self.service.download_resume(str(foreign.id))

    def test_content_returns_txt_text(self):
        result = self.service.resume_content(str(self.resume.id))
        self.assertIn("张三", result["content"])
        self.assertIn("13812345678", result["content"])

    def test_content_broken_docx_raises_400(self):
        broken = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        broken.write(b"not a docx zip")
        broken.close()
        docx_resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="bad.docx", extension="docx",
            file_path=broken.name, file_size=os.path.getsize(broken.name),
            sha256="sha-" + uuid.uuid7().hex, source_channel="OTHER", status="SUCCESS",
        )
        with self.assertRaisesRegex(AppApiException, "提取失败"):
            self.service.resume_content(str(docx_resume.id))

    def test_content_missing_file_raises_404(self):
        self.resume.file_path = "/tmp/not-exists-" + uuid.uuid7().hex + ".txt"
        self.resume.save(update_fields=["file_path"])
        with self.assertRaises(NotFound404):
            self.service.resume_content(str(self.resume.id))
```

- [ ] **步骤 2：运行测试确认失败**

```bash
uv run python apps/manage.py test hr.tests.ResumeDownloadTests --keepdb
```

预期：FAIL，`AttributeError: 'RecruitmentService' object has no attribute 'download_resume'`

- [ ] **步骤 3：实现服务方法**（`apps/hr/serializers/recruitment.py`，`delete_resume` 之后追加）

```python
    def _resume_file(self, resume_id):
        resume = ResumeFile.objects.filter(id=resume_id, workspace_id=self.workspace_id).first()
        if resume is None:
            raise NotFound404(404, "Resource not found")
        return resume

    def download_resume(self, resume_id):
        resume = self._resume_file(resume_id)
        if not os.path.exists(resume.file_path):
            raise NotFound404(404, "File not found")
        content_type = {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
        }.get(resume.extension.lower(), "application/octet-stream")
        return resume.file_path, resume.file_name, content_type

    def resume_content(self, resume_id):
        resume = self._resume_file(resume_id)
        if not os.path.exists(resume.file_path):
            raise NotFound404(404, "File not found")
        try:
            if resume.extension == "docx":
                text = extract_text_from_docx(resume.file_path)
            else:
                text = extract_text_from_txt(resume.file_path)
        except Exception as exc:
            raise AppApiException(400, "简历内容提取失败") from exc
        return {"content": text}
```

注意：`apps/hr/serializers/recruitment.py` 顶部 `os` 已导入（`upload_resumes` 使用 `os.path.getsize`），`extract_text_from_docx`/`extract_text_from_txt` 需追加（六期任务 2 删除了 `from hr.services.resume_parser import extract_text_from_docx, extract_text_from_txt`，现重新追加）。

- [ ] **步骤 4：新增视图与路由**

`apps/hr/views/recruitment.py` 的 `ResumeDetailAPI` 内追加嵌套类（`delete` 之后）：

```python
    class Download(APIView):
        authentication_classes = [TokenAuth]

        @member_required
        def get(self, request, workspace_id, resume_id):
            file_path, file_name, content_type = _service(request, workspace_id).download_resume(resume_id)
            try:
                handle = open(file_path, "rb")
            except OSError as exc:
                raise AppApiException(500, "文件读取失败") from exc
            return FileResponse(handle, content_type=content_type, as_attachment=True, filename=file_name)

    class Content(APIView):
        authentication_classes = [TokenAuth]

        @member_required
        def get(self, request, workspace_id, resume_id):
            return result.success(_service(request, workspace_id).resume_content(resume_id))
```

`apps/hr/views/recruitment.py` 顶部 import 追加：

```python
from django.http import FileResponse
```

`apps/hr/views/__init__.py`：追加 `CandidateCheckDuplicateAPI`、`ResumeDetailAPI` 无需（已导出）——检查现有导出，追加 `CandidateCheckDuplicateAPI`。

`apps/hr/urls.py` 中 `resumes/<str:resume_id>` 路由之后追加：

```python
    path("workspace/<str:workspace_id>/hr/resumes/<str:resume_id>/download", views.ResumeDetailAPI.Download.as_view()),
    path("workspace/<str:workspace_id>/hr/resumes/<str:resume_id>/content", views.ResumeDetailAPI.Content.as_view()),
```

- [ ] **步骤 5：运行测试确认通过**

```bash
uv run python apps/manage.py test hr.tests.ResumeDownloadTests --keepdb
```

预期：`Ran 6 tests ... OK`

- [ ] **步骤 6：Commit**

```bash
git add apps/hr/
git commit -m "feat(人事): 提供简历下载与原文查看"
```

---

### 任务 2：重复检测（TDD）

**文件：**
- 修改：`apps/hr/serializers/recruitment.py`
- 修改：`apps/hr/views/recruitment.py`、`apps/hr/views/__init__.py`、`apps/hr/urls.py`
- 修改：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的测试 `DuplicateDetectionTests`**

在 `apps/hr/tests.py` 末尾追加：

```python
class DuplicateDetectionTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
        self.alice = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13800000001", email="alice@example.com",
        )
        self.bob = Candidate.objects.create(
            name="Bob", workspace_id="workspace-a", phone="13800000001", email="bob@example.com",
        )
        self.carol = Candidate.objects.create(
            name="Carol", workspace_id="workspace-a", phone="13800000002", email="ALICE@example.com",
        )
        self.foreign = Candidate.objects.create(
            name="Dave", workspace_id="workspace-b", phone="13800000001", email="dave@example.com",
        )

    def test_page_marks_same_phone_and_email_as_duplicates(self):
        result = self.service.page_candidates(1, 20, {})
        by_id = {item["id"]: item for item in result["records"]}
        self.assertIn(str(self.bob.id), by_id[str(self.alice.id)]["duplicate_ids"])
        self.assertIn(str(self.alice.id), by_id[str(self.bob.id)]["duplicate_ids"])
        self.assertIn(str(self.carol.id), by_id[str(self.alice.id)]["duplicate_ids"])

    def test_page_does_not_mark_foreign_workspace(self):
        result = self.service.page_candidates(1, 20, {})
        by_id = {item["id"]: item for item in result["records"]}
        self.assertNotIn(str(self.foreign.id), by_id[str(self.alice.id)]["duplicate_ids"])
        self.assertEqual(by_id[str(self.carol.id)]["duplicate_ids"], [])

    def test_check_duplicate_by_phone_and_email(self):
        result = self.service.check_duplicate({"phone": "13800000001"})
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["id"], str(self.alice.id))
        result = self.service.check_duplicate({"email": "ALICE@example.com"})
        ids = {item["id"] for item in result["candidates"]}
        self.assertIn(str(self.alice.id), ids)
        self.assertIn(str(self.carol.id), ids)

    def test_check_duplicate_excludes_self(self):
        result = self.service.check_duplicate({"email": "alice@example.com", "exclude_id": str(self.alice.id)})
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["id"], str(self.carol.id))

    def test_check_duplicate_empty_returns_empty(self):
        result = self.service.check_duplicate({})
        self.assertEqual(result["candidates"], [])
```

- [ ] **步骤 2：运行测试确认失败**

```bash
uv run python apps/manage.py test hr.tests.DuplicateDetectionTests --keepdb
```

预期：FAIL——`page_candidates` 返回无 `duplicate_ids` 键（KeyError）、`check_duplicate` 不存在（AttributeError）

- [ ] **步骤 3：实现 `check_duplicate` 服务方法**（`apps/hr/serializers/recruitment.py`，`resume_content` 之后追加）

```python
    def check_duplicate(self, data):
        phone = data.get("phone")
        email = data.get("email")
        exclude_id = data.get("exclude_id")
        if (not isinstance(phone, str) or not phone.strip()) and (not isinstance(email, str) or not email.strip()):
            return {"candidates": []}
        queryset = Candidate.objects.filter(workspace_id=self.workspace_id)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        matches = []
        seen = set()
        if isinstance(phone, str) and phone.strip():
            for row in queryset.filter(phone=phone.strip()):
                if row.id not in seen:
                    seen.add(row.id)
                    matches.append(row)
        if isinstance(email, str) and email.strip():
            for row in queryset.filter(email__iexact=email.strip()):
                if row.id not in seen:
                    seen.add(row.id)
                    matches.append(row)
        return {
            "candidates": [
                {"id": str(row.id), "name": row.name, "phone": row.phone, "email": row.email, "current_city": row.current_city}
                for row in matches[:20]
            ]
        }
```

- [ ] **步骤 4：扩展 `page_candidates` 返回 `duplicate_ids`**

`apps/hr/serializers/recruitment.py` 的 `page_candidates` 中，构造 records 后追加（在 `return` 前）：

```python
        records = [self._candidate_output(candidate) for candidate in candidates]
        self._attach_duplicate_ids(records, candidates)
        return {"total": total, "records": records}
```

并新增私有方法（直接复用已查出的 candidates 对象，避免每记录重复查询）：

```python
    def _attach_duplicate_ids(self, records, candidates):
        for record, candidate in zip(records, candidates):
            dupes = set()
            if candidate.phone:
                dupes.update(
                    Candidate.objects.filter(workspace_id=self.workspace_id, phone=candidate.phone)
                    .exclude(id=candidate.id).values_list("id", flat=True)
                )
            if candidate.email:
                dupes.update(
                    Candidate.objects.filter(workspace_id=self.workspace_id, email__iexact=candidate.email)
                    .exclude(id=candidate.id).values_list("id", flat=True)
                )
            record["duplicate_ids"] = [str(item) for item in dupes]
```

注意：`page_candidates` 现有实现为 `return {"total": total, "records": [self._candidate_output(candidate) for candidate in records]}`——将其改写为上述两行结构（变量名 `candidates` 保持现状）。

- [ ] **步骤 5：新增视图与路由**

`apps/hr/views/recruitment.py` 追加（`CandidateDetailAPI` 之后）：

```python
class CandidateCheckDuplicateAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def post(self, request, workspace_id):
        return result.success(_service(request, workspace_id).check_duplicate(request.data))
```

`apps/hr/views/__init__.py`：import 与 `__all__` 追加 `CandidateCheckDuplicateAPI`。

`apps/hr/urls.py` 中 `candidates/<str:candidate_id>` 路由**之前**（注意顺序：`candidates/<str:candidate_id>` 会吞 `check-duplicate`）追加：

```python
    path("workspace/<str:workspace_id>/hr/candidates/check-duplicate", views.CandidateCheckDuplicateAPI.as_view()),
```

- [ ] **步骤 6：运行测试确认通过**

```bash
uv run python apps/manage.py test hr.tests.DuplicateDetectionTests --keepdb
```

预期：`Ran 5 tests ... OK`

- [ ] **步骤 7：Commit**

```bash
git add apps/hr/
git commit -m "feat(人事): 提供候选人重复检测"
```

---

### 任务 3：候选人合并（TDD）

**文件：**
- 修改：`apps/hr/serializers/recruitment.py`
- 修改：`apps/hr/views/recruitment.py`、`apps/hr/views/__init__.py`、`apps/hr/urls.py`
- 修改：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的测试 `CandidateMergeTests`**

在 `apps/hr/tests.py` 末尾追加：

```python
class CandidateMergeTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, is_workspace_manage=True)
        self.primary = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13800000001", skills=["Python"],
        )
        self.secondary = Candidate.objects.create(
            name="Alice Wang", workspace_id="workspace-a", email="alice@example.com",
            current_city="上海", years_experience=5, skills=["Python", "Django"], note="从简历解析",
        )

    def test_merge_fills_missing_fields_and_unions_skills(self):
        result = self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
        self.assertEqual(result["name"], "Alice")
        self.assertEqual(result["email"], "alice@example.com")
        self.assertEqual(result["current_city"], "上海")
        self.assertEqual(result["years_experience"], 5)
        self.assertEqual(result["skills"], ["Python", "Django"])
        self.assertIn("从简历解析", result["note"])
        self.assertFalse(Candidate.objects.filter(id=self.secondary.id).exists())

    def test_merge_migrates_resumes_and_assignments(self):
        job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="r.txt", extension="txt",
            file_path="/tmp/r.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            candidate=self.secondary,
        )
        assignment_id = self.service.create_assignment(job.id, self.secondary.id, {})["id"]
        interview = Interview.objects.create(workspace_id="workspace-a", assignment_id=assignment_id, round_no=1)
        self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
        resume.refresh_from_db()
        self.assertEqual(resume.candidate_id, self.primary.id)
        assignment = CandidateAssignment.objects.get(id=assignment_id)
        self.assertEqual(assignment.candidate_id, self.primary.id)
        interview.refresh_from_db()
        self.assertEqual(interview.assignment_id, assignment_id)

    def test_merge_rejects_conflicting_active_assignment(self):
        job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=2)
        self.service.create_assignment(job.id, self.primary.id, {})
        self.service.create_assignment(job.id, self.secondary.id, {})
        with self.assertRaisesRegex(AppApiException, "冲突"):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})

    def test_merge_allows_different_job_active_assignments(self):
        job_a = Job.objects.create(name="Engineer A", workspace_id="workspace-a", headcount=1)
        job_b = Job.objects.create(name="Engineer B", workspace_id="workspace-a", headcount=1)
        self.service.create_assignment(job_a.id, self.primary.id, {})
        self.service.create_assignment(job_b.id, self.secondary.id, {})
        self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
        self.assertFalse(Candidate.objects.filter(id=self.secondary.id).exists())

    def test_merge_rejects_self(self):
        with self.assertRaisesRegex(AppApiException, "自己"):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.primary.id)})

    def test_merge_cross_workspace_raises_404(self):
        foreign = Candidate.objects.create(name="Dave", workspace_id="workspace-b")
        with self.assertRaises(NotFound404):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(foreign.id)})

    def test_merge_requires_manage(self):
        member_service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, is_workspace_manage=False)
        with self.assertRaises(AppUnauthorizedFailed):
            member_service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})

    def test_merge_secondary_id_required(self):
        with self.assertRaisesRegex(AppApiException, "secondary_id is required"):
            self.service.merge_candidates(str(self.primary.id), {})

    def test_merge_archived_secondary_allowed(self):
        self.secondary.status = "ARCHIVED"
        self.secondary.save(update_fields=["status"])
        self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
        self.assertFalse(Candidate.objects.filter(id=self.secondary.id).exists())
```

- [ ] **步骤 2：运行测试确认失败**

```bash
uv run python apps/manage.py test hr.tests.CandidateMergeTests --keepdb
```

预期：FAIL，`AttributeError: 'RecruitmentService' object has no attribute 'merge_candidates'`

- [ ] **步骤 3：实现 `merge_candidates` 服务方法**（`apps/hr/serializers/recruitment.py`，`check_duplicate` 之后追加）

```python
    def merge_candidates(self, primary_id, data):
        self._require_manage()
        secondary_id = data.get("secondary_id")
        if not isinstance(secondary_id, str) or not secondary_id.strip():
            raise AppApiException(400, "secondary_id is required")
        primary = self._candidate(primary_id)
        secondary = self._candidate(secondary_id)
        if primary.id == secondary.id:
            raise AppApiException(400, "不能与自己合并")
        primary_jobs = set(
            CandidateAssignment.objects.filter(candidate=primary, status__in=ACTIVE_ASSIGNMENT_STATUSES)
            .values_list("job_id", flat=True)
        )
        if CandidateAssignment.objects.filter(
            candidate=secondary, status__in=ACTIVE_ASSIGNMENT_STATUSES, job_id__in=primary_jobs
        ).exists():
            raise AppApiException(400, "存在与主候选人冲突的有效指派，请先调整")
        with transaction.atomic():
            if not primary.name:
                primary.name = secondary.name
            if not primary.email:
                primary.email = secondary.email
            if not primary.phone:
                primary.phone = secondary.phone
            if not primary.current_city:
                primary.current_city = secondary.current_city
            if not primary.target_city:
                primary.target_city = secondary.target_city
            if not primary.highest_degree:
                primary.highest_degree = secondary.highest_degree
            if primary.years_experience is None:
                primary.years_experience = secondary.years_experience
            if not primary.source:
                primary.source = secondary.source
            primary.skills = primary.skills + [skill for skill in secondary.skills if skill not in primary.skills]
            primary.note = "\n".join(part for part in [primary.note, secondary.note] if part)
            primary.save()
            ResumeFile.objects.filter(candidate=secondary).update(candidate=primary)
            CandidateAssignment.objects.filter(candidate=secondary).update(candidate=primary)
            secondary.delete()
        return self.get_candidate(primary_id)
```

- [ ] **步骤 4：新增视图与路由**

`apps/hr/views/recruitment.py` 的 `CandidateDetailAPI` 内追加嵌套类：

```python
    class Merge(APIView):
        authentication_classes = [TokenAuth]

        @manage_required
        def post(self, request, workspace_id, candidate_id):
            return result.success(_service(request, workspace_id).merge_candidates(candidate_id, request.data))
```

`apps/hr/urls.py` 中 `candidates/<str:candidate_id>/archive` 路由之后追加：

```python
    path("workspace/<str:workspace_id>/hr/candidates/<str:candidate_id>/merge", views.CandidateDetailAPI.Merge.as_view()),
```

- [ ] **步骤 5：运行测试确认通过**

```bash
uv run python apps/manage.py test hr.tests.CandidateMergeTests --keepdb
```

预期：`Ran 9 tests ... OK`

- [ ] **步骤 6：运行 hr 全量确认无回归**

```bash
uv run python apps/manage.py test hr.tests --keepdb
```

预期：全部 OK（74 旧 + 6 + 5 + 9 = 94）

- [ ] **步骤 7：Commit**

```bash
git add apps/hr/
git commit -m "feat(人事): 提供候选人合并能力"
```

---

### 任务 4：前端类型与 API 封装

**文件：**
- 修改：`ui/src/api/type/hr.ts`
- 修改：`ui/src/api/hr/recruitment.ts`

- [ ] **步骤 1：在 `ui/src/api/type/hr.ts` 追加/修改类型**

`Candidate` 接口追加 `duplicate_ids?: string[]`；文件末尾追加：

```ts
export interface DuplicateCheckCandidate {
  id: string
  name: string
  phone: string
  email: string | null
  current_city: string
}
```

- [ ] **步骤 2：在 `ui/src/api/hr/recruitment.ts` 追加方法与导出**

import 追加 `DuplicateCheckCandidate`；文件末尾追加：

```ts
const getResumeContent = (resumeId: string) =>
  get(`${prefix.value}/resumes/${resumeId}/content`) as Promise<Result<{ content: string }>>

const downloadResume = (resumeId: string, fileName: string) =>
  exportFile(fileName, `${prefix.value}/resumes/${resumeId}/download`, {}, undefined)

const checkDuplicate = (data: Record<string, unknown>) =>
  post(`${prefix.value}/candidates/check-duplicate`, data) as Promise<Result<{ candidates: DuplicateCheckCandidate[] }>>

const mergeCandidates = (primaryId: string, secondaryId: string) =>
  post(`${prefix.value}/candidates/${primaryId}/merge`, { secondary_id: secondaryId }) as Promise<Result<CandidateDetail>>
```

import 追加 `exportFile`：

```ts
import { exportFile, del, get, post, put } from '@/request'
```

`export default` 追加：`checkDuplicate`、`downloadResume`、`getResumeContent`、`mergeCandidates`（字母序）。

- [ ] **步骤 3：类型检查**

```bash
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
```

预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add ui/src/api/
git commit -m "feat(人事): 新增简历查看下载与查重合并前端封装"
```

---

### 任务 5：候选人页功能接入

**文件：**
- 修改：`ui/src/views/hr/candidates/index.vue`

- [ ] **步骤 1：模板——操作列扩展与重复 tag**

候选人表格「技能」列后追加「重复」列：

```vue
        <el-table-column label="重复" width="110">
          <template #default="{ row }">
            <el-tooltip v-if="row.duplicate_ids?.length" :content="`与 ${row.duplicate_ids.length} 名候选人重复`" placement="top">
              <el-tag type="warning" size="small">疑似重复</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
```

操作列追加两个按钮（现有「编辑/加入职位/归档」之后）：

```vue
            <el-button link type="primary" @click="openResumeListDialog(row)">简历</el-button>
            <el-button v-if="isWorkspaceManage" link type="danger" :disabled="!row.duplicate_ids?.length" @click="openMergeDialog(row)">合并</el-button>
```

- [ ] **步骤 2：模板——简历列表对话框与内容查看对话框**

在 `assignmentDialogVisible` 对话框之后追加：

```vue
    <el-dialog v-model="resumeListVisible" title="简历" width="620px">
      <el-table :data="candidateResumes" size="small">
        <el-table-column prop="file_name" label="文件名" min-width="160" />
        <el-table-column prop="file_size" label="大小" width="90">
          <template #default="{ row }">{{ (row.file_size / 1024).toFixed(1) }} KB</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'SUCCESS' ? 'success' : row.status === 'FAILED' ? 'danger' : 'info'" size="small">
              {{ row.status === 'SUCCESS' ? '成功' : row.status === 'FAILED' ? '失败' : '解析中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="上传时间" min-width="150">
          <template #default="{ row }">{{ new Date(row.create_time).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button link type="primary" size="small" :disabled="row.status !== 'SUCCESS'" @click="viewResumeContent(row)">查看</el-button>
            <el-button link type="primary" size="small" @click="downloadResumeFile(row)">下载</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="resumeListVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="resumeContentVisible" title="简历原文" width="640px">
      <pre class="resume-content">{{ resumeContent }}</pre>
    </el-dialog>

    <el-dialog v-model="mergeDialogVisible" title="合并候选人" width="480px">
      <el-form label-width="96px">
        <el-form-item label="主候选人"><span>{{ mergingCandidate?.name }}</span></el-form-item>
        <el-form-item label="目标候选人">
          <el-select v-model="mergeTargetId" filterable placeholder="选择要合并进来的候选人" style="width: 100%">
            <el-option v-for="c in mergeCandidatesList" :key="c.id" :label="`${c.name}${c.phone ? ` · ${c.phone}` : ''}`" :value="c.id" />
          </el-select>
        </el-form-item>
        <div class="color-secondary">合并后目标候选人的简历与指派将迁移至主候选人，目标候选人被删除；存在冲突有效指派时将被拒绝。</div>
      </el-form>
      <template #footer><el-button @click="mergeDialogVisible = false">取消</el-button><el-button type="primary" :disabled="!mergeTargetId" :loading="saving" @click="confirmMerge">确认合并</el-button></template>
    </el-dialog>
```

- [ ] **步骤 3：script——状态与逻辑**

```ts
const resumeListVisible = ref(false)
const candidateResumes = ref<ResumeFile[]>([])
const resumeContentVisible = ref(false)
const resumeContent = ref('')
const mergingCandidate = ref<Candidate | null>(null)
const mergeDialogVisible = ref(false)
const mergeTargetId = ref('')
const mergeCandidatesList = ref<Candidate[]>([])

function openResumeListDialog(candidate: Candidate) {
  candidateResumes.value = []
  resumeListVisible.value = true
  HrApi.getCandidateResumes(candidate.id).then((response) => {
    candidateResumes.value = response.data
  })
}

function viewResumeContent(resume: ResumeFile) {
  resumeContent.value = ''
  resumeContentVisible.value = true
  HrApi.getResumeContent(resume.id).then((response) => {
    resumeContent.value = response.data.content
  })
}

function downloadResumeFile(resume: ResumeFile) {
  HrApi.downloadResume(resume.id, resume.file_name)
}

function openMergeDialog(candidate: Candidate) {
  mergingCandidate.value = candidate
  mergeTargetId.value = ''
  HrApi.getCandidates({ current_page: 1, page_size: 100 }, { status: '' }).then((response) => {
    mergeCandidatesList.value = response.data.records.filter((item) => item.id !== candidate.id)
    mergeDialogVisible.value = true
  })
}

function confirmMerge() {
  if (!mergingCandidate.value || !mergeTargetId.value) return
  saving.value = true
  HrApi.mergeCandidates(mergingCandidate.value.id, mergeTargetId.value)
    .then(() => {
      mergeDialogVisible.value = false
      MsgSuccess('候选人已合并')
      refresh()
    })
    .catch(() => {})
    .finally(() => {
      saving.value = false
    })
}
```

- [ ] **步骤 4：script——编辑保存前查重提示**

`saveCandidate` 改为先查重：

```ts
function saveCandidate() {
  if (!candidateForm.name.trim()) return
  const data = { ...candidateForm, skills: skillsText.value.split(',').map((skill) => skill.trim()).filter(Boolean) }
  HrApi.checkDuplicate({ phone: candidateForm.phone, email: candidateForm.email, exclude_id: editingCandidate.value?.id || '' })
    .then((response) => {
      if (response.data.candidates.length > 0) {
        MsgConfirm('发现疑似重复候选人', `有 ${response.data.candidates.length} 名候选人手机号或邮箱相同，是否继续保存？`, { type: 'warning' })
          .then(() => doSaveCandidate(data))
          .catch(() => {})
      } else {
        doSaveCandidate(data)
      }
    })
    .catch(() => {})
}

function doSaveCandidate(data: Record<string, unknown>) {
  saving.value = true
  const request = editingCandidate.value
    ? HrApi.updateCandidate(editingCandidate.value.id, data)
    : HrApi.createCandidate(data)
  request.then(() => {
    candidateDialogVisible.value = false
    MsgSuccess('候选人已保存')
    refresh()
  }).finally(() => { saving.value = false })
}
```

import 类型追加 `ResumeFile`：

```ts
import type { Candidate, Job, ResumeFile, ResumeUploadResult } from '@/api/type/hr'
```

- [ ] **步骤 5：style——原文查看样式**

```css
.resume-content {
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 480px;
  overflow-y: auto;
  margin: 0;
}
```

- [ ] **步骤 6：构建验证**

```bash
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build >/dev/null 2>&1 && echo ADMIN_OK
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat >/dev/null 2>&1 && echo CHAT_OK
```

预期：vue-tsc PASS、ADMIN_OK、CHAT_OK

- [ ] **步骤 7：Commit**

```bash
git add ui/src/views/hr/candidates/index.vue
git commit -m "feat(人事): 新增简历查看与候选人合并页面"
```

---

### 任务 6：全量验收与文档

**文件：**
- 修改：`README-hr.md`
- 修改：`docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md`

- [ ] **步骤 1：后端全量回归**

```bash
uv run python apps/manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb && uv run python apps/manage.py check && uv run python apps/manage.py makemigrations --check --dry-run
```

预期：全部 PASS（86 旧 + 20 新 = 106），check 无问题，无待生成迁移。

- [ ] **步骤 2：前端全量构建与产物扫描**

```bash
cd ui
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build >/dev/null 2>&1 && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat >/dev/null 2>&1
! rg -n '/(workflow|mcp_tools|text_to_speech|speech_to_text|play_demo_text)' dist/admin dist/chat && echo SCAN_OK
git diff --check
```

预期：vue-tsc PASS、构建 PASS、SCAN_OK、diff 无空白错误。

- [ ] **步骤 3：更新 `README-hr.md`**——在「人事六期验收」之前追加「人事七期验收」小节：

```markdown
## 人事七期验收（2026-08-13）

- 简历：候选人简历可下载原文件、可查看提取文本（docx/txt），跨工作区与文件缺失正确 404。
- 查重：列表标记疑似重复（同手机号/邮箱，邮箱忽略大小写）；新建/编辑保存前查重提示。
- 合并：主优先补充字段、技能并集、备注拼接，简历/指派迁移、从候选人删除；有效指派同职位冲突拒绝。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，106/106 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更。
- 前端：简历对话框、重复标记、合并对话框可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。
```

- [ ] **步骤 4：审计文档追加验收记录**（`docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md` 末尾）：

```markdown
---

## 人事七期验收记录（2026-08-13）

实现范围：简历下载（FileResponse 原文件流）与原文查看（实时提取）、候选人重复标记与编辑查重、候选人合并（主优先补充+关系迁移+冲突拒绝）。
本期未引入姓名模糊相似度检测、批量合并、合并历史审计。

| 验证项 | 结果 |
|--------|------|
| `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb` | 106/106 PASS |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected（无新迁移） |
| `ui: vue-tsc --build` | PASS |
| `ui: vite build` / `vite build --mode chat` | PASS；产物无已裁剪端点 |
| 下载/查看 | 200 附件流、缺失文件 404、跨工作区 404、损坏 docx 400、txt 内容一致均覆盖 |
| 查重 | 同手机号/邮箱标记（邮箱忽略大小写）、跨工作区排除、exclude 自身、空参数、编辑查重均覆盖 |
| 合并 | 字段补充/技能并集/备注拼接、简历与指派迁移、Interview 保留、同人 400、冲突指派 400、跨工作区 404、非 manage 无权限、归档从候选人合并均覆盖 |
```

- [ ] **步骤 5：Commit 验收记录**

```bash
git add README-hr.md docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md
git commit -m "test(人事): 记录简历查看合并与查重验收"
```

- [ ] **步骤 6：确认工作树干净**

```bash
git status --short
git log --oneline -8
```

预期：无未提交变更；最近 8 条提交覆盖七期全部提交（规格 54a3e1d/74dfeea 已在计划前完成）。
