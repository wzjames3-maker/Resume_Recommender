# 候选人恢复（ARCHIVED→ACTIVE）设计

## 背景

PRD §4.1 与 A3 能力矩阵均宣称招聘管理员可「候选人归档/恢复」，但代码中只有归档（PUT /candidates/{id}/archive）没有恢复：无路由、无服务方法、无前端按钮。候选人一旦归档即成为死路（见 HANDOFF.md §8.3 交接审计结论）。本文档补齐该缺口。

## 语义

- 恢复仅针对 ARCHIVED 状态：ARCHIVED → ACTIVE。
- DELETED 为匿名化终态，不可恢复（与 edit/archive/merge 的「终态不可复活」口径一致）。
- ACTIVE 已是可用状态，恢复无意义，拒绝（与 reopen_job 对非 ON_HOLD/CLOSED 职位报错的口径一致）。
- 恢复不改变历史指派记录（含终态指派），仅恢复候选人可继续建立/流转指派的能力。
- 归档前置条件（无进行中指派）在归档时已强制；恢复不校验指派（终态指派可随候选人一并恢复为可再投递状态，由既有状态机与 create_assignment 的 status == ACTIVE 校验接管）。

## API

统一前缀：/admin/api/workspace/{workspace_id}/hr。

| 方法 | 路径 | 用途 | 权限 |
|---|---|---|---|
| PUT | /candidates/{candidate_id}/restore | 恢复候选人（ARCHIVED→ACTIVE） | ADMIN |

- 跨工作区 404（复用 _candidate）。
- DELETED → 400「deleted candidate cannot be restored」。
- 非 ARCHIVED → 400「Candidate is not archived」。
- 服务层 _require_manage() 与路由 hr_admin_required 双层校验（与 archive/delete 一致），非 ADMIN 403 并写 ACCESS_DENIED 审计。
- 成功写 RESTORE 审计（object_type=CANDIDATE，HrAuditAction.RESTORE 已定义，与指派误拒绝恢复的 RESTORE/ASSIGNMENT 区分）。

## 服务方法

RecruitmentService.restore_candidate(candidate_id)：

1. _require_manage()
2. _candidate(candidate_id)（跨工作区 404）
3. status == DELETED → 400
4. status != ARCHIVED → 400
5. status = ACTIVE，save(update_fields=["status", "update_time"])
6. write_audit_log(workspace_id, user_id, "RESTORE", "CANDIDATE", candidate.id)
7. 返回 _candidate_output(candidate)

## 前端

- ui/src/api/hr/recruitment.ts：新增 restoreCandidate(candidateId)（PUT /candidates/{id}/restore）并导出。
- 列表操作列（candidates/index.vue）：ARCHIVED 行显示「恢复」按钮（ADMIN 可见，success 类型），确认弹窗后调用并刷新。
- 详情抽屉 footer：ARCHIVED 且 ADMIN 时显示「恢复」按钮，成功后刷新详情与列表。

## 测试

- 服务层：恢复后 status == ACTIVE 且可再次创建指派（闭环）；DELETED 拒绝；ACTIVE 拒绝；非 ADMIN 403 且写 ACCESS_DENIED 审计；跨工作区 404；写 RESTORE 审计。
- 路由层：ADMIN PUT /candidates/{id}/restore 200；OPERATOR 403 + ACCESS_DENIED 审计。

## 验收

HR 全量测试 PASS（231 基线 + 新增用例）、makemigrations --check --dry-run 无漂移、ruff check apps/hr/ 干净、前端 vue-tsc PASS、HANDOFF.md §8.3 缺口标记为已修复。
