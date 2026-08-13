# 简历上传与结构化解析实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 `apps/hr` 实现简历批量上传、规则型结构化解析、同工作区去重和候选人检索扩展。

**架构：** 新增 `ResumeFile` 模型存储原文件与解析状态；上传在请求内同步解析，抽取字段后创建或关联候选人；按 `(workspace_id, sha256)` 唯一约束去重；候选人列表检索在现有 `page_candidates` 上增加过滤。

**技术栈：** Python 3.11、Django 5.2、DRF、python-docx、Vue 3、Element Plus。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `apps/hr/models/recruitment.py` | 新增 `ResumeFile` 模型、`ResumeStatus`、`ResumeChannel` 枚举与唯一约束。 |
| `apps/hr/migrations/0003_resumefile.py` | 创建简历表与 `(workspace_id, sha256)` 唯一约束。 |
| `apps/hr/services/resume_parser.py` | docx/txt 文本提取与规则字段抽取。 |
| `apps/hr/serializers/recruitment.py` | `RecruitmentService` 增加简历上传、列表、删除与检索过滤。 |
| `apps/hr/views/recruitment.py` | 简历上传、详情列表、删除视图。 |
| `apps/hr/urls.py` | 注册简历 API 路由。 |
| `apps/hr/tests.py` | 解析、去重、隔离、大小/格式拒绝与权限测试。 |
| `ui/src/api/hr/recruitment.ts` | 增加简历上传、列表、删除调用。 |
| `ui/src/api/type/hr.ts` | 增加 `ResumeFile` 类型。 |
| `ui/src/views/hr/candidates/index.vue` | 增加上传简历入口、结果展示与技能/年限/来源检索。 |
| `ui/src/views/hr/candidates/detail.vue` | 新增候选人详情抽屉，展示简历列表。 |

### 任务 1：新增 ResumeFile 模型、迁移与解析服务

**文件：**
- 修改：`apps/hr/models/recruitment.py`
- 创建：`apps/hr/services/__init__.py`
- 创建：`apps/hr/services/resume_parser.py`
- 创建：`apps/hr/migrations/0003_resumefile.py`
- 测试：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的模型与解析测试**

在 `apps/hr/tests.py` 追加：

```python
from hr.models import ResumeChannel, ResumeFile, ResumeStatus
from hr.services.resume_parser import parse_resume_text


class ResumeParserTests(TestCase):
    def test_extracts_contact_and_profile_fields(self):
        text = (
            "姓名：张三\n电话：13812345678\n邮箱：zhangsan@example.com\n"
            "现居城市：杭州\n期望城市：上海\n最高学历：本科\n5年工作经验\n"
            "专业技能：Python, Django, PostgreSQL"
        )
        result = parse_resume_text(text)
        self.assertEqual(result["name"], "张三")
        self.assertEqual(result["phone"], "13812345678")
        self.assertEqual(result["email"], "zhangsan@example.com")
        self.assertEqual(result["current_city"], "杭州")
        self.assertEqual(result["target_city"], "上海")
        self.assertEqual(result["highest_degree"], "本科")
        self.assertEqual(result["years_experience"], 5)
        self.assertEqual(result["skills"], ["Python", "Django", "PostgreSQL"])

    def test_unknown_fields_stay_empty(self):
        result = parse_resume_text("这是一个没有结构化字段的文本")
        self.assertEqual(result["name"], "")
        self.assertEqual(result["email"], "")
        self.assertEqual(result["phone"], "")
        self.assertEqual(result["skills"], [])


class ResumeFileModelTests(TestCase):
    def test_duplicate_sha256_in_same_workspace_rejected(self):
        from django.db import IntegrityError, transaction

        ResumeFile.objects.create(file_name="a.txt", extension="txt", file_path="/tmp/a.txt",
                                  file_size=1, sha256="abc", workspace_id="w1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ResumeFile.objects.create(file_name="b.txt", extension="txt", file_path="/tmp/b.txt",
                                          file_size=1, sha256="abc", workspace_id="w1")

    def test_same_sha256_different_workspace_allowed(self):
        ResumeFile.objects.create(file_name="a.txt", extension="txt", file_path="/tmp/a.txt",
                                  file_size=1, sha256="abc", workspace_id="w1")
        ResumeFile.objects.create(file_name="b.txt", extension="txt", file_path="/tmp/b.txt",
                                  file_size=1, sha256="abc", workspace_id="w2")
        self.assertEqual(ResumeFile.objects.count(), 2)
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.ResumeParserTests hr.tests.ResumeFileModelTests --keepdb
```

预期：FAIL，提示 `No module named 'hr.services'` 或 `Cannot import name 'ResumeFile'`。

- [ ] **步骤 3：实现模型与解析服务**

在 `apps/hr/models/recruitment.py` 追加：

```python
class ResumeStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"


class ResumeChannel(models.TextChoices):
    REFERRAL = "REFERRAL", "Referral"
    JOB_SITE = "JOB_SITE", "Job site"
    HEADHUNTER = "HEADHUNTER", "Headhunter"
    CAMPUS = "CAMPUS", "Campus"
    OTHER = "OTHER", "Other"


class ResumeFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    file_name = models.CharField(max_length=255)
    extension = models.CharField(max_length=16)
    file_path = models.CharField(max_length=1024)
    file_size = models.IntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    source_channel = models.CharField(max_length=20, choices=ResumeChannel.choices, default=ResumeChannel.OTHER)
    status = models.CharField(max_length=16, choices=ResumeStatus.choices, default=ResumeStatus.PENDING)
    error_message = models.TextField(blank=True, default="")
    candidate = models.ForeignKey(Candidate, on_delete=models.SET_NULL, null=True, blank=True)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_resume_file"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "sha256"], name="hr_unique_resume_sha256_per_workspace")
        ]
```

创建 `apps/hr/services/resume_parser.py`：

```python
import re

_DEGREES = ["博士", "硕士", "本科", "大专", "中专", "高中"]


def _extract_after(text: str, patterns) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1).strip().strip(":：，,。;；")
            if value:
                return value
    return ""


def _split_skills(section: str) -> list:
    if not section:
        return []
    parts = re.split(r"[，,、;；/|]\s*", section.strip())
    return [part.strip() for part in parts if part.strip()]


def parse_resume_text(text: str) -> dict:
    name = _extract_after(text, [r"姓名[:：]\s*(.{2,8}?)(?:\n|$)", r"(?:姓名)?\s*[:：]?\s*(.{2,4}?)(?:\n|$)"])
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    phone_match = re.search(r"(?:\+?86[- ]?)?1[3-9]\d{9}", text)
    current_city = _extract_after(text, [r"(?:现居|现居住|所在城市)[:：]\s*([\u4e00-\u9fa5]{2,10}?)(?:\n|$)"])
    target_city = _extract_after(text, [r"(?:期望城市|意向城市|目标城市)[:：]\s*([\u4e00-\u9fa5]{2,10}?)(?:\n|$)"])
    degree = ""
    for value in _DEGREES:
        if re.search(re.escape(value), text):
            degree = value
            break
    years_match = re.search(r"(\d+)\s*年(?:工作经验|经验|工作经历)|工作\s*(\d+)\s*年", text)
    years = int(years_match.group(1) or years_match.group(2)) if years_match else None
    skills = _split_skills(_extract_after(text, [r"(?:技能|专业技能|掌握技能|专业技能)[:：]\s*([^\n]{1,500})(?:\n|$)"]))

    note_parts = []
    for section_name, patterns in (
        ("教育经历", [r"教育经历[:：]?\s*\n(.*?)(?:\n\s*(?:工作经历|项目经历|自我评价)|$)"]),
        ("工作经历", [r"工作经历[:：]?\s*\n(.*?)(?:\n\s*(?:教育经历|项目经历|自我评价)|$)"]),
    ):
        section = _extract_after(text, patterns)
        if section:
            note_parts.append(f"{section_name}：{section.strip()}")

    return {
        "name": name,
        "email": email_match.group(0) if email_match else "",
        "phone": phone_match.group(0) if phone_match else "",
        "current_city": current_city,
        "target_city": target_city,
        "highest_degree": degree,
        "years_experience": years,
        "skills": skills,
        "note": "\n".join(note_parts),
    }


def extract_text_from_docx(file_path: str) -> str:
    from docx import Document

    document = Document(file_path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_text_from_txt(file_path: str) -> str:
    for encoding in ("utf-8", "gbk"):
        try:
            with open(file_path, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError:
            continue
    raise ValueError("无法解码文本文件")
```

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
uv run python apps/manage.py test hr.tests.ResumeParserTests hr.tests.ResumeFileModelTests --keepdb
```

预期：生成 `0003_resumefile.py`；4 个测试 PASS。

- [ ] **步骤 5：提交模型与解析**

```bash
git add apps/hr/models apps/hr/services apps/hr/migrations
git commit -m "feat(人事): 新增简历模型与规则解析"
```

### 任务 2：实现简历上传、列表、删除 API 与检索扩展

**文件：**
- 修改：`apps/hr/serializers/recruitment.py`
- 修改：`apps/hr/views/recruitment.py`
- 修改：`apps/hr/urls.py`
- 测试：`apps/hr/tests.py`

- [ ] **步骤 1：编写失败的领域测试**

在 `apps/hr/tests.py` 追加：

```python
import tempfile
from pathlib import Path

from hr.services.resume_parser import extract_text_from_docx


class ResumeServiceTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, is_workspace_manage=True)

    def _txt_file(self, content: str, name: str = "resume.txt"):
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write(content.encode("utf-8"))
        handle.close()
        return handle.name, name, "txt"

    def test_upload_creates_candidate_and_marks_success(self):
        path, name, ext = self._txt_file("姓名：李四\n电话：13912345678\n3年工作经验")
        result = self.service.upload_resumes([(path, name, ext)], "OTHER")
        self.assertEqual(result[0]["status"], "SUCCESS")
        self.assertIsNotNone(result[0]["candidate_id"])
        self.assertEqual(result[0]["duplicate"], False)

    def test_duplicate_upload_reuses_candidate(self):
        path, name, ext = self._txt_file("姓名：王五\n邮箱：wangwu@example.com")
        first = self.service.upload_resumes([(path, name, ext)], "OTHER")[0]
        second = self.service.upload_resumes([(path, name, ext)], "OTHER")[0]
        self.assertEqual(second["duplicate"], True)
        self.assertEqual(second["candidate_id"], first["candidate_id"])
        self.assertEqual(Candidate.objects.count(), 1)

    def test_reject_unsupported_extension_and_oversize(self):
        with self.assertRaisesRegex(AppApiException, "not supported"):
            self.service.upload_resumes([("/tmp/x.pdf", "x.pdf", "pdf")], "OTHER")
        big = "a" * (21 * 1024 * 1024)
        path, name, ext = self._txt_file(big)
        with self.assertRaisesRegex(AppApiException, "20"):
            self.service.upload_resumes([(path, name, ext)], "OTHER")

    def test_duplicate_upload_marks_failed_and_keeps_previous(self):
        path, name, ext = self._txt_file("姓名：赵六")
        first = self.service.upload_resumes([(path, name, ext)], "OTHER")[0]
        self.service.upload_resumes([(path, name, ext)], "OTHER")
        first_resume = ResumeFile.objects.get(id=first["resume_id"])
        self.assertEqual(first_resume.status, "SUCCESS")
```

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
MAXKB_CONFIG_TYPE=ENV MAXKB_DB_HOST=127.0.0.1 MAXKB_DB_PORT=5432 \
MAXKB_DB_NAME=maxkb MAXKB_DB_USER=postgres MAXKB_DB_PASSWORD=maxkb-test \
MAXKB_REDIS_HOST=127.0.0.1 MAXKB_REDIS_PORT=6379 MAXKB_REDIS_DB=0 \
uv run python apps/manage.py test hr.tests.ResumeServiceTests --keepdb
```

预期：FAIL，提示 `upload_resumes` 未定义。

- [ ] **步骤 3：实现服务方法与 API 视图**

在 `apps/hr/serializers/recruitment.py` 追加方法。关键实现要点：

```python
_RESUME_EXTENSIONS = {"docx", "txt"}
_RESUME_MAX_SIZE = 20 * 1024 * 1024


def _resume_dir(self):
    path = os.path.join(PROJECT_DIR, "data", "resume", self.workspace_id)
    os.makedirs(path, exist_ok=True)
    return path


def upload_resumes(self, files, source_channel):
    if source_channel not in ResumeChannel.values:
        raise AppApiException(400, "source_channel is invalid")
    records = []
    for file_path, file_name, extension in files:
        extension = extension.lower()
        if extension not in _RESUME_EXTENSIONS:
            raise AppApiException(400, f"File format {extension} is not supported")
        size = os.path.getsize(file_path)
        if size > _RESUME_MAX_SIZE:
            raise AppApiException(400, "File exceeds 20 MB limit")
        digest = hashlib.sha256()
        with open(file_path, "rb") as handle:
            digest.update(handle.read())
        sha256 = digest.hexdigest()
        existing = ResumeFile.objects.filter(workspace_id=self.workspace_id, sha256=sha256).first()
        if existing:
            records.append({
                "resume_id": str(existing.id), "file_name": existing.file_name,
                "status": existing.status, "sha256": existing.sha256,
                "duplicate": True, "candidate_id": str(existing.candidate_id) if existing.candidate_id else None,
            })
            continue
        stored = os.path.join(self._resume_dir(), f"{sha256}.{extension}")
        os.replace(file_path, stored)
        try:
            if extension == "docx":
                text = extract_text_from_docx(stored)
            else:
                text = extract_text_from_txt(stored)
            parsed = parse_resume_text(text)
            candidate = Candidate.objects.create(
                workspace_id=self.workspace_id, user_id=self.user_id,
                name=parsed["name"] or file_name, email=parsed["email"] or None,
                phone=parsed["phone"], current_city=parsed["current_city"],
                target_city=parsed["target_city"], highest_degree=parsed["highest_degree"],
                years_experience=parsed["years_experience"], skills=parsed["skills"],
                source=source_channel, note=parsed["note"],
            )
            resume = ResumeFile.objects.create(
                workspace_id=self.workspace_id, file_name=file_name, extension=extension,
                file_path=stored, file_size=size, sha256=sha256,
                source_channel=source_channel, status=ResumeStatus.SUCCESS, candidate=candidate,
                user_id=self.user_id,
            )
            status = "SUCCESS"
        except Exception as exc:
            resume = ResumeFile.objects.create(
                workspace_id=self.workspace_id, file_name=file_name, extension=extension,
                file_path=stored, file_size=size, sha256=sha256,
                source_channel=source_channel, status=ResumeStatus.FAILED,
                error_message=str(exc), user_id=self.user_id,
            )
            status = "FAILED"
        records.append({
            "resume_id": str(resume.id), "file_name": resume.file_name,
            "status": resume.status, "sha256": resume.sha256,
            "duplicate": False, "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
        })
    return records
```

在 `apps/hr/views/recruitment.py` 增加 `ResumeAPI`（多文件上传）与 `ResumeDetailAPI`（列表/删除），并注册到 `apps/hr/urls.py`：

```python
path("workspace/<str:workspace_id>/hr/candidates/resumes", views.ResumeAPI.as_view()),
path("workspace/<str:workspace_id>/hr/candidates/<str:candidate_id>/resumes", views.ResumeListAPI.as_view()),
path("workspace/<str:workspace_id>/hr/resumes/<str:resume_id>", views.ResumeDetailAPI.as_view()),
```

同时在 `RecruitmentService.page_candidates` 中增加 `skills`、`years_min`、`source` 过滤：

```python
if query.get("skills"):
    for skill in query["skills"].split(","):
        queryset = queryset.filter(skills__contains=[skill.strip()])
if query.get("years_min"):
    queryset = queryset.filter(years_experience__gte=int(query["years_min"]))
if query.get("source"):
    queryset = queryset.filter(source=query["source"])
```

上传视图使用 `MultiPartParser`，把 `request.FILES.getlist("files")` 先落临时文件再调用服务。

- [ ] **步骤 4：运行 HR 测试、Django 检查与迁移检查**

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

- [ ] **步骤 5：提交 API 与检索扩展**

```bash
git add apps/hr
git commit -m "feat(人事): 提供简历上传解析与检索扩展 API"
```

### 任务 3：实现管理端简历上传与检索 UI

**文件：**
- 修改：`ui/src/api/type/hr.ts`
- 修改：`ui/src/api/hr/recruitment.ts`
- 修改：`ui/src/views/hr/candidates/index.vue`

- [ ] **步骤 1：扩展类型与 API 客户端**

在 `ui/src/api/type/hr.ts` 追加：

```typescript
export type ResumeStatus = 'PENDING' | 'SUCCESS' | 'FAILED'
export type ResumeChannel = 'REFERRAL' | 'JOB_SITE' | 'HEADHUNTER' | 'CAMPUS' | 'OTHER'

export interface ResumeFile {
  id: string
  file_name: string
  extension: string
  file_size: number
  sha256: string
  source_channel: ResumeChannel
  status: ResumeStatus
  error_message: string
  candidate_id: string | null
  create_time: string
}
```

在 `ui/src/api/hr/recruitment.ts` 追加：

```typescript
const uploadResumes = (files: File[], sourceChannel: string) => {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  formData.append('source_channel', sourceChannel)
  return post(`${prefix.value}/candidates/resumes`, formData)
}

const getCandidateResumes = (candidateId: string) =>
  get(`${prefix.value}/candidates/${candidateId}/resumes`) as Promise<Result<ResumeFile[]>>

const deleteResume = (resumeId: string) => del(`${prefix.value}/resumes/${resumeId}`) as Promise<Result<boolean>>
```

`uploadResumes` 需使用 `multipart/form-data` 请求，参考项目内 `post` 对 `FormData` 的处理。

- [ ] **步骤 2：候选人页增加上传、结果与检索 UI**

候选人页：

- 顶部工具栏增加「上传简历」按钮和来源渠道下拉（`REFERRAL`/`JOB_SITE`/`HEADHUNTER`/`CAMPUS`/`OTHER`）。
- 上传使用隐藏 `<input type="file" multiple accept=".docx,.txt">`，提交后逐条展示：成功（显示候选人名）、重复（提示既有候选人）、失败（显示 `error_message`）。
- 检索区增加技能、最低工作年限、来源筛选，绑定 `filters` 并传入 `getCandidates`。
- 候选人行操作增加「简历」入口，打开详情抽屉显示 `getCandidateResumes` 返回的列表。

- [ ] **步骤 3：运行类型检查确认通过**

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
git add ui/src/api/hr ui/src/api/type/hr.ts ui/src/views/hr
git commit -m "feat(人事): 新增简历上传与检索页面"
```

### 任务 4：端到端验收与审计记录

**文件：**
- 修改：`README-hr.md`
- 修改：`docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md`

- [ ] **步骤 1：运行完整后端回归**

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

- [ ] **步骤 2：复跑前端检查与产物扫描**

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

在 `README-hr.md` 与审计文档追加「人事二期验收」：简历上传、去重、解析回填、检索过滤、格式/大小拒绝与权限测试结果。

- [ ] **步骤 4：提交验收记录**

```bash
git add README-hr.md docs/superpowers/audits/2026-08-13-local-core-slimming-baseline.md
git commit -m "test(人事): 记录简历上传与解析验收"
```

## 自检结果

- 规格覆盖：ResumeFile 模型、解析规则、去重、API、前端、检索与测试均有对应任务。
- 占位符：计划未使用待定实现或未定义步骤。
- 类型一致性：`ResumeFile`、`ResumeStatus`、`ResumeChannel`、`upload_resumes` 在所有任务中名称一致。
