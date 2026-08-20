# 简历库测试补齐 B 报告（2026-08-20）

> 对应人事部收敛建议 B：`ResumeDatabase` 0 覆盖补齐（增删改查 + 上传带库 + `ResumeFile.save()` 总库兜底）

## 1. 背景

- `ResumeDatabase` / `ResumeDatabaseMembership` / `ResumeFile.save()` 在 `apps/hr/tests.py` 中覆盖率为 0，仅在 `test_agent_scope.py` 间接使用
- 业务风险：总库强制、`upload_resumes` 多库、去重复用、归档阻断、低层 `save()` 兜底均无回归，线上易出现跨库污染或无库简历

## 2. 本次新增（`apps/hr/tests.py::ResumeDatabaseCrudTests` 7 例）

| 用例 | 覆盖点 | 关键断言 |
|---|---|---|
| `test_total_auto_created_on_list` | 总库自动创建、重复名 400 | `GET /hr/resume-databases` 首次 1 条 `总库/is_system`，同名 `POST` 400 |
| `test_create_and_list_business_database` | 业务库增查、列表排序、权限 | `POST 业务库 200`，`GET` 2 条 `总库→业务库`，重复名 400，`VIEWER 403` |
| `test_total_cannot_be_archived_and_business_archive` | 归档、幂等、租户隔离 | `PUT /archive` 总库 400，业务库 200→`ARCHIVED`，二次幂等 200，跨 workspace 404 |
| `test_upload_with_business_database_creates_both_memberships` | 上传带库、双成员、兼容字段 | `POST /hr/candidates/resumes` with `resume_database_ids=biz` → `resume_database_ids {total,biz}`，`resume_database == total`，`membership 2`，`parse task called` |
| `test_duplicate_upload_adds_missing_membership` | 去重复用、增量成员 | 同 `sha256` 先 total 后 biz → `duplicate true/false`，`ResumeFile count 1`，`membership 1→2`，`delay called 1` |
| `test_archived_database_blocks_upload` | 归档阻断 | 归档后 `POST` with `biz` 404，`count 0`，`delay 0` |
| `test_resumefile_save_low_level_ensures_total` | `ResumeFile.save()` 总库兜底（裸 ORM） | A: 指定 `business` 仍补 `total membership`；B: 全新 workspace 无库时 `save()` 自动建 `总库` 并 `membership 1` |

> 7 例均在 `hr.tests.ResumeDatabaseCrudTests` 中，使用 `APIClient` + `SimpleUploadedFile` + `patch(parse_resume_task.delay)`，workspace 隔离为 `ws-resume-db-b` / `ws-fresh-total-ensure`

## 3. 验证

```bash
uv run ruff check apps/hr/tests.py  # All checks passed
MAXKB_CONFIG_TYPE=ENV ... uv run python apps/manage.py test hr.tests.ResumeDatabaseCrudTests --keepdb -v 2  # 7 OK
MAXKB_CONFIG_TYPE=ENV ... uv run python apps/manage.py test hr.tests --keepdb  # 466 OK
pnpm exec vue-tsc --build  # 0
```

- `ResumeFile.save()` 的 `DEFERRABLE` 与 `get_or_create` 在 `0028` 迁移后已通过 `test_resumefile_save_low_level_ensures_total` 覆盖
- `list_resume_databases` 的 `annotate(resume_count/candidate_count/pending_count)` 在 `test_total_auto_created_on_list` 与上传用例中间接覆盖

## 4. 影响

- `ResumeDatabase` 从 0 覆盖提升至 **7 例**，与 `RESUME-DATABASES.md` §6-7 的「总库强制、业务库多选、跨库复用、归档阻断、成员关系为准」一一对应
- 上传带库与低层 `save()` 的总库兜底现由回归守护，B 可视为收敛

## 5. 文件

- 变更：`apps/hr/tests.py`（+287 行，`ResumeDatabaseCrudTests`）
- 报告：`docs/HR-RESUME-DB-B-2026-08-20.md`（本文）

