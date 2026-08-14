# HR 六期实现计划：Celery 异步化简历解析与批量上传队列

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 简历解析从请求内同步执行改为每文件一个 Celery 任务（QueueOnce 防重），上传立即返回 PENDING，前端轮询 batch-status 收敛状态。

**架构：** 任务函数 `parse_resume_task(resume_id)`（`apps/hr/task/resume.py`，同步可调、`transaction.atomic` 内建候选人+更新简历）→ `upload_resumes` 保留校验/查重/落库并派发任务 → 新增 `GET /hr/resumes/batch-status` 批量查询 → 前端上传对话框轮询展示。

**技术栈：** Celery（`ops.celery` app、Redis broker、celery-once QueueOnce）、Django 5.2、Vue 3.5。

**规格：** `docs/superpowers/specs/2026-08-13-hr-resume-async-design.md`

---

## 文件结构

- 创建 `apps/hr/task/__init__.py`（空包）
- 创建 `apps/hr/task/resume.py`：`parse_resume_task`（任务 1）
- 修改 `apps/ops/celery/__init__.py`：imports 追加 `'hr.task.resume'`（任务 1）
- 修改 `apps/hr/serializers/recruitment.py`：`upload_resumes` 异步化 + `batch_resume_status`（任务 2、3）
- 修改 `apps/hr/views/recruitment.py`：新增 `ResumeBatchStatusAPI`（任务 3）
- 修改 `apps/hr/views/__init__.py`、`apps/hr/urls.py`：注册（任务 3）
- 修改 `apps/hr/tests.py`：`ResumeParseTaskTests`、`ResumeServiceTests` 适配、`ResumeBatchStatusTests`（任务 1、2、3）
- 修改 `ui/src/api/type/hr.ts`：`ResumeBatchStatus` 类型（任务 4）
- 修改 `ui/src/api/hr/recruitment.ts`：`getResumeBatchStatus`（任务 4）
- 修改 `ui/src/views/hr/candidates/index.vue`：上传轮询（任务 5）
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

**基线**：hr.tests 单独 64 个测试；四 app 全量 76 个。

---

### 任务 1：异步任务函数（TDD）

**文件：**
- 创建：`apps/hr/task/__init__.py`、`apps/hr/task/resume.py`
- 修改：`apps/ops/celery/__init__.py`
- 修改：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的测试 `ResumeParseTaskTests`**

在 `apps/hr/tests.py` 末尾追加：

```python
class ResumeParseTaskTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()

    def _resume(self, content, extension="txt", workspace_id="workspace-a"):
        handle = tempfile.NamedTemporaryFile(suffix=f".{extension}", delete=False)
        handle.write(content.encode("utf-8"))
        handle.close()
        return ResumeFile.objects.create(
            workspace_id=workspace_id, file_name=f"r.{extension}", extension=extension,
            file_path=handle.name, file_size=os.path.getsize(handle.name),
            sha256="sha-" + uuid.uuid7().hex, source_channel="OTHER",
            status=ResumeStatus.PENDING, user_id=self.user_id,
        )

    def test_task_parses_and_creates_candidate(self):
        resume = self._resume("姓名：李四\n电话：13912345678\n3年工作经验")
        parse_resume_task.run(str(resume.id))
        resume.refresh_from_db()
        self.assertEqual(resume.status, "SUCCESS")
        self.assertIsNotNone(resume.candidate)
        self.assertEqual(resume.candidate.name, "李四")
        self.assertEqual(resume.candidate.phone, "13912345678")
        self.assertEqual(resume.candidate.source, "OTHER")

    def test_task_marks_failed_on_parse_error(self):
        resume = self._resume("not a docx zip", extension="docx")
        parse_resume_task.run(str(resume.id))
        resume.refresh_from_db()
        self.assertEqual(resume.status, "FAILED")
        self.assertTrue(resume.error_message)
        self.assertIsNone(resume.candidate)

    def test_task_ignores_missing_resume(self):
        parse_resume_task.run(str(uuid.uuid7()))
```

并更新 `apps/hr/tests.py` 顶部 import：

当前顶部（前 10 行）为：

```python
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
import uuid_utils.compat as uuid

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import AssignmentStatus, Candidate, CandidateAssignment, HrConfig, Interview, Job, ResumeFile
```

改为：

```python
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
import uuid_utils.compat as uuid

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import AssignmentStatus, Candidate, CandidateAssignment, HrConfig, Interview, Job, ResumeFile, ResumeStatus
from hr.task.resume import parse_resume_task
```

- [ ] **步骤 2：运行测试确认失败**

```bash
uv run python apps/manage.py test hr.tests.ResumeParseTaskTests --keepdb
```

预期：FAIL，`ModuleNotFoundError: No module named 'hr.task.resume'`

- [ ] **步骤 3：创建 `apps/hr/task/resume.py`**

```python
# coding=utf-8
from celery_once import QueueOnce
from django.db import transaction

from hr.models import Candidate, ResumeFile, ResumeStatus
from hr.services.resume_parser import extract_text_from_docx, extract_text_from_txt, parse_resume_text
from ops import celery_app


@celery_app.task(base=QueueOnce, once={"keys": ["resume_id"]}, name="celery:hr_parse_resume")
def parse_resume_task(resume_id):
    resume = ResumeFile.objects.filter(id=resume_id).first()
    if resume is None:
        return
    try:
        if resume.extension == "docx":
            text = extract_text_from_docx(resume.file_path)
        else:
            text = extract_text_from_txt(resume.file_path)
        parsed = parse_resume_text(text)
        with transaction.atomic():
            candidate = Candidate.objects.create(
                workspace_id=resume.workspace_id,
                user_id=resume.user_id,
                name=parsed["name"] or resume.file_name,
                email=parsed["email"] or None,
                phone=parsed["phone"],
                current_city=parsed["current_city"],
                target_city=parsed["target_city"],
                highest_degree=parsed["highest_degree"],
                years_experience=parsed["years_experience"],
                skills=parsed["skills"],
                source=resume.source_channel,
                note=parsed["note"],
            )
            resume.candidate = candidate
            resume.status = ResumeStatus.SUCCESS
            resume.error_message = ""
            resume.save(update_fields=["candidate", "status", "error_message", "update_time"])
    except Exception as exc:
        resume.status = ResumeStatus.FAILED
        resume.error_message = str(exc)
        resume.save(update_fields=["status", "error_message", "update_time"])
```

- [ ] **步骤 4：在 `apps/ops/celery/__init__.py` 的 `imports` 列表追加 `'hr.task.resume'`**

```python
    imports=[
        'knowledge.task.embedding',
        'knowledge.task.generate',
        'knowledge.task.sync',
        'hr.task.resume',
    ]
```

- [ ] **步骤 5：运行测试确认通过**

```bash
uv run python apps/manage.py test hr.tests.ResumeParseTaskTests --keepdb
```

预期：`Ran 3 tests ... OK`

- [ ] **步骤 6：Commit**

```bash
git add apps/hr/task/ apps/ops/celery/__init__.py apps/hr/tests.py
git commit -m "feat(人事): 提供简历解析异步任务"
```

---

### 任务 2：上传接口异步化（TDD）

**文件：**
- 修改：`apps/hr/serializers/recruitment.py`
- 修改：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的测试——适配既有 `ResumeServiceTests` 并新增派发断言**

在 `apps/hr/tests.py` 的 `ResumeServiceTests` 中替换两个用例：

`test_upload_creates_candidate_and_marks_success` 替换为：

```python
    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_upload_creates_pending_and_dispatches_task(self, mock_delay):
        path, name, ext = self._txt_file("姓名：李四\n电话：13912345678\n3年工作经验")
        result = self.service.upload_resumes([(path, name, ext)], "OTHER")
        self.assertEqual(result[0]["status"], "PENDING")
        self.assertIsNone(result[0]["candidate_id"])
        self.assertEqual(result[0]["duplicate"], False)
        self.assertEqual(mock_delay.call_count, 1)
        resume = ResumeFile.objects.get(id=result[0]["resume_id"])
        self.assertEqual(resume.status, "PENDING")
```

`test_duplicate_upload_keeps_first_success` 替换为（首次上传后是 PENDING，断言 duplicate 命中时沿用记录状态且不新增）：

```python
    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_duplicate_upload_keeps_first_record(self, mock_delay):
        path, name, ext = self._txt_file("姓名：赵六")
        first = self.service.upload_resumes([(path, name, ext)], "OTHER")[0]
        self.assertEqual(first["status"], "PENDING")
        path2, _, _ = self._txt_file("姓名：赵六")
        second = self.service.upload_resumes([(path2, name, ext)], "OTHER")[0]
        self.assertEqual(second["duplicate"], True)
        self.assertEqual(second["candidate_id"], first["candidate_id"])
        self.assertEqual(ResumeFile.objects.count(), 1)
        self.assertEqual(mock_delay.call_count, 1)
```

在 `ResumeServiceTests` 内追加两个新用例：

```python
    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_upload_dispatch_already_queued_raises_500(self, mock_delay):
        from celery_once import AlreadyQueued

        mock_delay.side_effect = AlreadyQueued(5)
        path, name, ext = self._txt_file("姓名：周七")
        with self.assertRaisesRegex(AppApiException, "任务已存在"):
            self.service.upload_resumes([(path, name, ext)], "OTHER")

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_upload_dispatch_error_marks_failed(self, mock_delay):
        mock_delay.side_effect = RuntimeError("broker down")
        path, name, ext = self._txt_file("姓名：吴八")
        result = self.service.upload_resumes([(path, name, ext)], "OTHER")
        self.assertEqual(result[0]["status"], "FAILED")
        self.assertTrue(result[0]["error_message"])
        resume = ResumeFile.objects.get(id=result[0]["resume_id"])
        self.assertEqual(resume.status, "FAILED")
```

注意：`test_duplicate_upload_reuses_candidate` 与 `test_reject_unsupported_extension_and_oversize` 保留不变（duplicate 与校验逻辑同步）。但 `test_duplicate_upload_reuses_candidate` 中首次上传会真实 `delay` 到 Redis（未被 mock）——测试环境 Redis 可用，`delay` 会真正入队。为避免测试间污染与对 broker 的依赖，将该用例改为（仅追加 mock，断言不变）：

```python
    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_duplicate_upload_reuses_candidate(self, mock_delay):
        path, name, ext = self._txt_file("姓名：王五\n邮箱：wangwu@example.com")
        first = self.service.upload_resumes([(path, name, ext)], "OTHER")[0]
        path2, _, _ = self._txt_file("姓名：王五\n邮箱：wangwu@example.com")
        second = self.service.upload_resumes([(path2, name, ext)], "OTHER")[0]
        self.assertEqual(second["duplicate"], True)
        self.assertEqual(second["candidate_id"], first["candidate_id"])
        self.assertEqual(Candidate.objects.count(), 0)
        self.assertEqual(ResumeFile.objects.count(), 1)
```

注意：`candidate_id` 现在首次上传也是 None（异步建人），duplicate 命中时返回 existing 记录的 `candidate_id` 同样为 None，断言 `second["candidate_id"] == first["candidate_id"]` 仍成立。

- [ ] **步骤 2：运行测试确认失败**

```bash
uv run python apps/manage.py test hr.tests.ResumeServiceTests --keepdb
```

预期：FAIL——新断言要求 PENDING 而现实现返回 SUCCESS。

- [ ] **步骤 3：改造 `apps/hr/serializers/recruitment.py` 的 `upload_resumes`**

顶部 import 追加：

```python
from celery_once import AlreadyQueued
from hr.task.resume import parse_resume_task
```

`upload_resumes` 中「存储文件后的解析段」替换为（duplicate 分支与校验段保留不变）：

```python
            stored = os.path.join(self._resume_dir(), f"{sha256}.{extension}")
            shutil.move(file_path, stored)
            resume = ResumeFile.objects.create(
                workspace_id=self.workspace_id, file_name=file_name, extension=extension,
                file_path=stored, file_size=size, sha256=sha256,
                source_channel=source_channel, status=ResumeStatus.PENDING, user_id=self.user_id,
            )
            try:
                parse_resume_task.delay(str(resume.id))
                status = ResumeStatus.PENDING
                error_message = ""
            except AlreadyQueued as exc:
                raise AppApiException(500, "任务已存在，请稍后查询") from exc
            except Exception as exc:
                resume.status = ResumeStatus.FAILED
                resume.error_message = str(exc)
                resume.save(update_fields=["status", "error_message", "update_time"])
                status = ResumeStatus.FAILED
                error_message = str(exc)
            records.append({
                "resume_id": str(resume.id),
                "file_name": resume.file_name,
                "status": status,
                "sha256": resume.sha256,
                "duplicate": False,
                "candidate_id": None,
                "error_message": error_message,
            })
        return records
```

（原解析段——提取文本、parse、建 Candidate、SUCCESS/FAILED 分支——整体删除。）

- [ ] **步骤 4：运行测试确认通过**

```bash
uv run python apps/manage.py test hr.tests.ResumeServiceTests --keepdb
```

预期：该测试类全部 OK（含两个新增用例）

- [ ] **步骤 5：Commit**

```bash
git add apps/hr/serializers/recruitment.py apps/hr/tests.py
git commit -m "feat(人事): 上传接口异步派发解析任务"
```

---

### 任务 3：批量状态查询接口（TDD）

**文件：**
- 修改：`apps/hr/serializers/recruitment.py`
- 修改：`apps/hr/views/recruitment.py`、`apps/hr/views/__init__.py`、`apps/hr/urls.py`
- 修改：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的测试 `ResumeBatchStatusTests`**

在 `apps/hr/tests.py` 末尾追加：

```python
class ResumeBatchStatusTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)

    def _resume(self, status="PENDING"):
        return ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="r.txt", extension="txt",
            file_path="/tmp/r.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            source_channel="OTHER", status=status,
        )

    def test_batch_status_returns_only_existing(self):
        r1 = self._resume()
        r2 = self._resume("FAILED")
        result = self.service.batch_resume_status([str(r1.id), str(r2.id), str(uuid.uuid7())])
        self.assertEqual(len(result), 2)
        by_id = {item["resume_id"]: item for item in result}
        self.assertEqual(by_id[str(r1.id)]["status"], "PENDING")
        self.assertEqual(by_id[str(r2.id)]["status"], "FAILED")
        self.assertEqual(by_id[str(r2.id)]["error_message"], "")

    def test_batch_status_filters_by_workspace(self):
        foreign = ResumeFile.objects.create(
            workspace_id="workspace-b", file_name="f.txt", extension="txt",
            file_path="/tmp/f.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
        )
        result = self.service.batch_resume_status([str(foreign.id)])
        self.assertEqual(result, [])
```

- [ ] **步骤 2：运行测试确认失败**

```bash
uv run python apps/manage.py test hr.tests.ResumeBatchStatusTests --keepdb
```

预期：FAIL，`AttributeError: 'RecruitmentService' object has no attribute 'batch_resume_status'`

- [ ] **步骤 3：实现服务方法**（`apps/hr/serializers/recruitment.py`，`delete_resume` 之后追加）

```python
    def batch_resume_status(self, resume_ids):
        resumes = ResumeFile.objects.filter(workspace_id=self.workspace_id, id__in=resume_ids)
        return [
            {
                "resume_id": str(resume.id),
                "file_name": resume.file_name,
                "status": resume.status,
                "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
                "error_message": resume.error_message,
            }
            for resume in resumes
        ]
```

- [ ] **步骤 4：新增视图与路由**

`apps/hr/views/recruitment.py` 末尾追加：

```python
class ResumeBatchStatusAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def get(self, request, workspace_id):
        ids_param = request.query_params.get("ids", "")
        resume_ids = [item.strip() for item in ids_param.split(",") if item.strip()]
        if not resume_ids:
            raise AppApiException(400, "ids is required")
        if len(resume_ids) > 200:
            raise AppApiException(400, "too many ids")
        return result.success(_service(request, workspace_id).batch_resume_status(resume_ids))
```

`apps/hr/views/recruitment.py` 顶部 import 追加 `AppApiException`：

```python
from common.exception.app_exception import AppApiException
```

`apps/hr/views/__init__.py`：import 与 `__all__` 追加 `ResumeBatchStatusAPI`。

`apps/hr/urls.py` 末尾追加：

```python
    path("workspace/<str:workspace_id>/hr/resumes/batch-status", views.ResumeBatchStatusAPI.as_view()),
```

- [ ] **步骤 5：运行测试确认通过并补视图参数校验冒烟**

```bash
uv run python apps/manage.py test hr.tests.ResumeBatchStatusTests --keepdb
```

预期：`Ran 2 tests ... OK`

在 `ResumeBatchStatusTests` 追加视图层校验用例（走服务层等价断言无需 HTTP；视图仅参数校验，直接以服务层方法测不足的部分用路由冒烟——沿用五期 `AiRouteSmokeTests` 模式）：

```python
class ResumeBatchStatusRouteTests(TestCase):
    def test_route_is_registered_and_protected(self):
        response = self.client.get("/admin/api/workspace/workspace-a/hr/resumes/batch-status?ids=a")
        self.assertIn(response.status_code, (401, 403))
```

- [ ] **步骤 6：运行 hr 全量确认无回归**

```bash
uv run python apps/manage.py test hr.tests --keepdb
```

预期：全部 OK（64 旧 + 3 任务 1 + 2 上传净增 + 3 状态查询 = 72）

- [ ] **步骤 7：Commit**

```bash
git add apps/hr/
git commit -m "feat(人事): 提供简历批量状态查询接口"
```

---

### 任务 4：前端类型与 API 封装

**文件：**
- 修改：`ui/src/api/type/hr.ts`
- 修改：`ui/src/api/hr/recruitment.ts`

- [ ] **步骤 1：在 `ui/src/api/type/hr.ts` 追加类型**

```ts
export interface ResumeBatchStatus {
  resume_id: string
  file_name: string
  status: 'PENDING' | 'SUCCESS' | 'FAILED'
  candidate_id: string | null
  error_message: string
}
```

- [ ] **步骤 2：在 `ui/src/api/hr/recruitment.ts` 追加方法与导出**

import 追加 `ResumeBatchStatus`；文件末尾（`extractSkills` 之后）追加：

```ts
const getResumeBatchStatus = (ids: string[]) =>
  get(`${prefix.value}/resumes/batch-status`, { ids: ids.join(',') }) as Promise<Result<ResumeBatchStatus[]>>
```

`export default` 追加 `getResumeBatchStatus`（字母序：getResumes 之后）。

- [ ] **步骤 3：类型检查**

```bash
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
```

预期：PASS

- [ ] **步骤 4：Commit**

```bash
git add ui/src/api/
git commit -m "feat(人事): 新增简历批量状态查询前端封装"
```

---

### 任务 5：前端上传轮询

**文件：**
- 修改：`ui/src/views/hr/candidates/index.vue`

- [ ] **步骤 1：模板——上传结果状态标签支持「解析中」**

将上传结果行的 `el-tag` 改为三态：

```vue
              <el-tag :type="record.status === 'SUCCESS' ? 'success' : record.status === 'FAILED' ? 'danger' : 'info'" size="small">
                {{ record.status === 'SUCCESS' ? '成功' : record.status === 'FAILED' ? '失败' : '解析中' }}
              </el-tag>
```

- [ ] **步骤 2：script——轮询逻辑**

`handleResumeFiles` 改造（上传后若有 PENDING 则启动轮询）：

```ts
function handleResumeFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  input.value = ''
  if (files.length === 0) return
  uploadDialogVisible.value = true
  HrApi.uploadResumes(files, uploadChannel.value)
    .then((response) => {
      uploadResults.value = response.data
      const pendingIds = uploadResults.value.filter((record) => record.status === 'PENDING').map((record) => record.resume_id)
      if (pendingIds.length > 0) startResumePolling(pendingIds)
      else finishResumeUpload()
    })
    .catch(() => {})
}

function finishResumeUpload() {
  const failed = uploadResults.value.some((record) => record.status === 'FAILED')
  if (failed) MsgError('部分简历解析失败，请查看结果')
  else MsgSuccess('简历解析完成')
  refresh()
}

function startResumePolling(ids: string[]) {
  stopResumePolling()
  const endsAt = Date.now() + 60 * 1000
  resumePollTimer = setInterval(() => {
    HrApi.getResumeBatchStatus(ids)
      .then((response) => {
        const statusMap = new Map(response.data.map((item) => [item.resume_id, item]))
        let allDone = true
        for (const record of uploadResults.value) {
          const latest = statusMap.get(record.resume_id)
          if (!latest) continue
          record.status = latest.status
          record.error_message = latest.error_message || ''
          if (latest.status === 'PENDING') allDone = false
        }
        if (allDone || Date.now() > endsAt) {
          stopResumePolling()
          finishResumeUpload()
        }
      })
      .catch(() => {})
  }, 1000)
}

function stopResumePolling() {
  if (resumePollTimer) {
    clearInterval(resumePollTimer)
    resumePollTimer = null
  }
}
```

script 状态与生命周期追加：

```ts
const resumePollTimer = ref<ReturnType<typeof setInterval> | null>(null)

watch(uploadDialogVisible, (visible) => {
  if (!visible) stopResumePolling()
})

onUnmounted(stopResumePolling)
```

（`watch`、`onUnmounted` 从 `vue` 导入——候选页当前 import 为 `{ computed, onMounted, reactive, ref }`，追加 `onUnmounted`、`watch`。）

- [ ] **步骤 3：构建验证**

```bash
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build >/dev/null 2>&1 && echo ADMIN_OK
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat >/dev/null 2>&1 && echo CHAT_OK
```

预期：vue-tsc PASS、ADMIN_OK、CHAT_OK

- [ ] **步骤 4：Commit**

```bash
git add ui/src/views/hr/candidates/index.vue
git commit -m "feat(人事): 上传结果轮询展示解析进度"
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

预期：全部 PASS（76 旧 + 8 新 = 84），check 无问题，无待生成迁移。

- [ ] **步骤 2：前端全量构建与产物扫描**

```bash
cd ui
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vue-tsc --build
NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build >/dev/null 2>&1 && NODE_OPTIONS=--max-old-space-size=6144 pnpm exec vite build --mode chat >/dev/null 2>&1
! rg -n '/(workflow|mcp_tools|text_to_speech|speech_to_text|play_demo_text)' dist/admin dist/chat && echo SCAN_OK
git diff --check
```

预期：vue-tsc PASS、构建 PASS、SCAN_OK、diff 无空白错误。

- [ ] **步骤 3：可选端到端验证**——若本机可启动 celery worker：

```bash
# 终端 1（后台）：
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 uv run python apps/manage.py celery -A ops worker -l info --pool=solo >/tmp/hr-celery-worker.log 2>&1 &
# 验证：上传一个真实 txt 简历（curl multipart），轮询 batch-status 至 SUCCESS，候选人落库
```

若 worker 无法在本机稳定运行，跳过并记录原因（不阻塞验收）。

- [ ] **步骤 4：更新 `README-hr.md`**——在「人事五期验收」之前追加「人事六期验收」小节：

```markdown
## 人事六期验收（2026-08-13）

- 异步解析：简历上传后每文件一个 Celery 解析任务（QueueOnce 防重），立即返回 PENDING，前端轮询收敛状态。
- 状态查询：`GET /hr/resumes/batch-status` 批量查询（上限 200），跨工作区隔离。
- 失败处理：解析失败写 FAILED + error_message，可删除重传；派发 AlreadyQueued 返回 500 提示。
- 测试：`hr.tests application.tests knowledge.tests models_provider.tests`，84/84 PASS。
- 检查：`manage.py check` 无问题；`makemigrations --check --dry-run` 无变更（无新迁移）。
- 前端：上传对话框轮询展示解析进度可构建；`vue-tsc`、管理端和聊天端 Vite 构建均 PASS。
```

- [ ] **步骤 5：审计文档追加验收记录**（`docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md` 末尾）：

```markdown
---

## 人事六期验收记录（2026-08-13）

实现范围：简历解析 Celery 异步化（每文件一任务 + QueueOnce）、上传接口异步派发、批量状态查询接口、前端上传轮询。
本期未引入任务自动重试、上传历史页、简历下载与候选人合并（七期）。

| 验证项 | 结果 |
|--------|------|
| `manage.py test hr.tests application.tests knowledge.tests models_provider.tests --keepdb` | 84/84 PASS |
| `manage.py check` | System check identified no issues (0 silenced) |
| `manage.py makemigrations --check --dry-run` | No changes detected（无新迁移） |
| `ui: vue-tsc --build` | PASS |
| `ui: vite build` / `vite build --mode chat` | PASS；产物无已裁剪端点 |
| 任务函数 | 成功建候选人+SUCCESS、损坏文件 FAILED+error_message、缺失简历静默、事务原子性均覆盖 |
| 上传/查询 | PENDING+派发、duplicate 同步判定、AlreadyQueued 500、派发异常降级 FAILED、ids 上限 200、跨工作区隔离、路由冒烟均覆盖 |
```

- [ ] **步骤 6：Commit 验收记录**

```bash
git add README-hr.md docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md
git commit -m "test(人事): 记录简历解析异步化验收"
```

- [ ] **步骤 7：确认工作树干净**

```bash
git status --short
git log --oneline -8
```

预期：无未提交变更；最近 8 条提交覆盖六期全部提交（规格 01b2fbf/e44c7b1 已在计划前完成）。
