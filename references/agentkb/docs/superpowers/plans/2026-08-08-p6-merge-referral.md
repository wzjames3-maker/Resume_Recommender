# P6 查重合并与内推归属（F12 剩余）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 完成 F12 剩余工作——查重**合并动作**（重复候选人与主体合并，以最新解析值 + 人工 override 为准，保留全部简历文件与历史）与**内推归属**展示（候选人详情返回 source_channel/referrer，列表支持 referrer 筛选）。查重检测（姓名 + phone/email hash → pending_review）与来源渠道采集已在 P2 落地，不做改动。

**架构：** 新增 `candidate_merge` 服务与 `POST /candidates/{id}/merge` 端点。合并语义：被并入候选人的 `CandidateRevision/CandidateEmbedding/ResumeFile/CandidateEvent/CandidateOverride` 全部重挂到主体；主体 `latest_revision_id` 指向两人全 revision 中 created_at 最新一条，`structured_data/search_text/name` 同步为该最新解析值；override 两人全部保留（按 created_at 应用，人工修正永不自动覆盖）；被并入候选人 → deleted（30 天可恢复）。`candidate_events` 新增 `merged` 事件类型（String(32) 纯 Python 改，无需迁移）。

**技术栈：** FastAPI、SQLAlchemy 2.0（async）、pydantic v2、pytest、React（前端）。

**参考：** `docs/PRD.md` §7.2 F12、§7.2 F9 权限矩阵、`docs/superpowers/specs/2026-08-07-resume-schema-and-import.md` §2（字段优先级/override/合并关系）、P4 `candidate_view.py`/`candidate_lifecycle.py`。

---

## 设计决策与歧义裁决（实现前必读）

| # | 歧义 / 取舍 | 依据 | 本计划裁决 |
|---|------------|------|-----------|
| N-1 | 合并数据基准 | PRD F12「合并后以最新简历的解析值 + 人工修正 override 为准」；spec §2「与查重合并的关系」 | 两人全 revision 中 created_at 最新一条的 candidate_json 为合并 base；主体 `structured_data`/`search_text`/`name` 同步；override 两人全部保留（重挂主体，按 created_at 应用，人工修正永不自动覆盖） |
| N-2 | 被并入候选人去向 | PRD F12「保留全部简历文件与历史记录」；F8 生命周期 | 被并入者的 revision/嵌入/文件/事件/override 全部重挂到主体；被并入者 → deleted（30 天可恢复为独立候选人，其数据以主体副本为准） |
| N-3 | 合并权限与约束 | F9 矩阵「字段修正/删除/恢复/合并 允许」，但「进行中指派或 hired 默认拒绝删除/合并」 | member+；主体与被并入者须可见且非 deleted；任一 hired → 409；`base_revision_id`（主体 latest_revision_id）不匹配 → 409 |
| N-4 | 合并留痕 | PRD F12「全部写操作入审计日志」；F8 时间线 | `candidate_events` 新增 `merged` 类型（String(32) 纯 Python 改，无需迁移）；主体追加 merged 事件；审计 `candidate.merged` |
| N-5 | 内推归属展示 | PRD F12；spec v0.5（referrer 已冻结在 ParseRun） | 候选人详情补 `source_channel`/`referrer`（经最新 ResumeFile→ParseRun）；列表新增 `referrer` 筛选（EXISTS 子查询，防 JOIN 放大） |
| N-6 | 合并后索引 | spec §2「派生值联动」 | 主体 `search_text` 重写触发 search_tsv trigger；五段向量随 revision 重挂自动生效（向量 JOIN 按 revision_id 匹配最新 revision） |

---

## 文件结构

```
backend/
  app/models/
    candidate_event.py                        (修改：CandidateEventType 增加 merged)
  app/services/
    candidate_merge.py                        (新：merge_candidates + MergeError/MergeConflictError)
    candidate_list.py                         (修改：referrer 筛选)
  app/api/
    candidates.py                             (修改：POST /merge + 详情 source_channel/referrer + 列表 referrer)
  tests/
    test_candidate_merge.py                   (新)
    test_candidates_api.py                    (修改：merge API + referrer 回归)
  frontend/src/
    api/candidates.ts                         (修改：mergeCandidates)
    pages/CandidatesPage.tsx                  (修改：referrer 筛选输入)
    pages/CandidateDetailPage.tsx             (修改：来源/内推人展示 + 合并入口)
```

**领域边界**：P6 不改 P2 解析流水线/P3 搜人/P5 职位；`referrer` 解析与采集已冻结，仅新增展示与筛选。无新表/新列，**无需迁移**。

---

### 任务 1：merged 事件类型 + 合并服务

**文件：**
- 修改：`backend/app/models/candidate_event.py`
- 创建：`backend/app/services/candidate_merge.py`
- 测试：`backend/tests/test_candidate_merge.py`

**验收（N-1/N-2/N-4）：** 合并后主体以最新 revision 为 base、override 保留、被并入者重挂后软删；事件/状态正确。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidate_merge.py
import pytest


@pytest.mark.asyncio
async def test_merge_candidates_reparents_and_uses_latest_revision():
    from datetime import UTC, datetime, timedelta

    from app.core.database import SessionLocal
    from app.models import (
        Candidate, CandidateEvent, CandidateEventType, CandidateOverride,
        CandidateRevision, CandidateStatus, OverrideAction, ResumeFile, User, Workspace,
    )
    from app.services.candidate_merge import MergeConflictError, merge_candidates

    async with SessionLocal() as db:
        owner = User(email="cm-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cm-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()

        primary = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                            structured_data={"city": "杭州"}, search_text="杭州",
                            phone_hash="h1", email_hash=None)
        db.add(primary)
        await db.flush()
        rev_old = CandidateRevision(candidate_id=primary.id, run_id="cm-old", revision_id="cm-old:rev1",
                                    candidate_json={"name": "张三", "city": "杭州"}, evidence={},
                                    profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev_old)
        await db.flush()
        primary.latest_revision_id = rev_old.id
        db.add(CandidateOverride(candidate_id=primary.id, revision_id="cm-old:rev1", field_path="city",
                                 before_value="杭州", after_value="上海", action=OverrideAction.override, actor_id=owner.id))

        absorbed = Candidate(workspace_id=ws.id, status=CandidateStatus.pending_review, name="张三",
                             structured_data={"skills": ["Java"], "city": "北京"}, search_text="Java",
                             phone_hash="h2", email_hash="e2")
        db.add(absorbed)
        await db.flush()
        rev_new = CandidateRevision(candidate_id=absorbed.id, run_id="cm-new", revision_id="cm-new:rev1",
                                    candidate_json={"name": "张三", "skills": ["Java"], "city": "北京"}, evidence={},
                                    profile_json={"values": {"level": "Senior"}, "evidence": {}})
        db.add(rev_new)
        await db.flush()
        absorbed.latest_revision_id = rev_new.id
        db.add(ResumeFile(run_id="cm-new", candidate_id=absorbed.id, file_hash="f1", storage_key="k1",
                          format="pdf", file_size=1, content_type="application/pdf"))

        await db.commit()
        p_id, a_id, base = primary.id, absorbed.id, primary.latest_revision_id

        merged = await merge_candidates(db, primary=primary, absorbed=absorbed,
                                        base_revision_id=base, actor_id=owner.id)
        await db.commit()

        got = await db.get(Candidate, merged.id)
        assert got.latest_revision_id == rev_new.id  # 最新 revision 成为主体 base
        assert got.structured_data["skills"] == ["Java"]
        assert got.phone_hash == "h1"  # 主体已有 phone，保留
        assert got.email_hash == "e2"  # 主体无 email，用被并入者补齐
        # 被并入者软删
        absorbed2 = await db.get(Candidate, a_id)
        assert absorbed2.status is CandidateStatus.deleted
        assert absorbed2.deleted_until is not None
        # revision 重挂
        revs = (await db.execute(
            __import__("sqlalchemy").select(CandidateRevision.candidate_id)
            .where(CandidateRevision.id.in_([rev_old.id, rev_new.id])))).scalars().all()
        assert set(revs) == {p_id, p_id}
        # 事件
        evt = (await db.execute(
            __import__("sqlalchemy").select(CandidateEvent)
            .where(CandidateEvent.candidate_id == p_id, CandidateEvent.event_type == CandidateEventType.merged))).scalar_one()
        assert evt.detail["absorbed_id"] == a_id


@pytest.mark.asyncio
async def test_merge_conflict_and_hired_rejected():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, User, Workspace
    from app.services.candidate_merge import MergeError, merge_candidates

    async with SessionLocal() as db:
        owner = User(email="cm2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cm2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        primary = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                            structured_data={}, search_text="")
        absorbed = Candidate(workspace_id=ws.id, status=CandidateStatus.hired, name="张三",
                             structured_data={}, search_text="")
        db.add_all([primary, absorbed])
        await db.commit()

        with pytest.raises(MergeError, match="入职员工"):
            await merge_candidates(db, primary=primary, absorbed=absorbed,
                                   base_revision_id=primary.latest_revision_id, actor_id=owner.id)
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_candidate_merge.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：增加 merged 事件类型**

`backend/app/models/candidate_event.py` 的 `CandidateEventType` 增加 `merged = "merged"`：

```python
class CandidateEventType(str, enum.Enum):
    created = "created"
    status_changed = "status_changed"
    field_override = "field_override"
    note = "note"
    restored = "restored"
    purged = "purged"
    merged = "merged"
```

> 说明：`event_type` 列是 `String(32)`（非 PG enum），新增枚举值纯 Python 改动，无需迁移。

- [x] **步骤 4：实现合并服务**

```python
# backend/app/services/candidate_merge.py
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Candidate,
    CandidateEmbedding,
    CandidateEvent,
    CandidateEventType,
    CandidateOverride,
    CandidateRevision,
    CandidateStatus,
    ResumeFile,
)
from app.services.resume.segments import build_search_text


class MergeError(Exception):
    pass


class MergeConflictError(Exception):
    pass


_HISTORY_MODELS = (CandidateRevision, CandidateEmbedding, ResumeFile, CandidateEvent, CandidateOverride)


async def merge_candidates(db: AsyncSession, *, primary: Candidate, absorbed: Candidate,
                           base_revision_id: int, actor_id: int) -> Candidate:
    """合并重复候选人（N-1/N-2）：被并入者的历史重挂到主体，主体以最新 revision 为 base。"""
    if primary.id == absorbed.id:
        raise MergeError("不能与自身合并")
    if base_revision_id != primary.latest_revision_id:
        raise MergeConflictError("候选人已被修改，请刷新后重试")
    if CandidateStatus.hired in (primary.status, absorbed.status):
        raise MergeError("入职员工不可合并")
    if CandidateStatus.deleted in (primary.status, absorbed.status):
        raise MergeError("已删除候选人不可合并")

    # 1) 历史重挂（revision/嵌入/文件/事件/override 全部并入主体，保留全部简历与历史）
    for model in _HISTORY_MODELS:
        await db.execute(update(model).where(model.candidate_id == absorbed.id).values(candidate_id=primary.id))

    # 2) 最新 revision = 两人全 revision 中 created_at 最晚一条 → 合并 base
    newest = (await db.execute(select(CandidateRevision).where(
        CandidateRevision.candidate_id == primary.id)
        .order_by(CandidateRevision.created_at.desc(), CandidateRevision.id.desc()))).scalars().first()
    if newest is None:
        raise MergeError("无可合并的解析记录")
    primary.latest_revision_id = newest.id
    base = dict(newest.candidate_json)
    primary.structured_data = base
    primary.search_text = build_search_text(base)  # 触发 search_tsv 同步（N-6）
    primary.name = base.get("name") or primary.name

    # 3) PII 补缺：主体无 phone/email 时用被并入者的（人工已确认合并主体）
    if not primary.phone_hash and absorbed.phone_hash:
        primary.phone_enc, primary.phone_hash = absorbed.phone_enc, absorbed.phone_hash
    if not primary.email_hash and absorbed.email_hash:
        primary.email_enc, primary.email_hash = absorbed.email_enc, absorbed.email_hash

    # 4) 被并入者 → deleted（30 天可恢复；其数据已并入主体副本）
    absorbed.status = CandidateStatus.deleted
    absorbed.deleted_until = datetime.now(UTC) + timedelta(days=30)

    # 5) 主体追加 merged 事件（N-4）
    db.add(CandidateEvent(candidate_id=primary.id, event_type=CandidateEventType.merged,
                          title=f"合并候选人 {absorbed.id}",
                          detail={"absorbed_id": absorbed.id, "absorbed_name": absorbed.name},
                          actor_id=actor_id))
    return primary
```

- [x] **步骤 5：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_candidate_merge.py -v`
预期：PASS

- [x] **步骤 6：Commit**

```bash
git add backend/app/models/candidate_event.py backend/app/services/candidate_merge.py backend/tests/test_candidate_merge.py
git commit -m "feat: add candidate merge service and merged event (P6 F12)"
```

---

### 任务 2：合并 API + 内推归属展示

**文件：**
- 修改：`backend/app/api/candidates.py`
- 修改：`backend/app/services/candidate_list.py`
- 测试：`backend/tests/test_candidates_api.py`（追加）

**验收（N-3/N-5）：** `POST /candidates/{id}/merge`（member+，hired/deleted 409，base_revision_id 409）；详情返回 `source_channel`/`referrer`；列表支持 `referrer` 筛选。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidates_api.py 追加
@pytest.mark.asyncio
async def test_merge_candidates_api_and_referrer_detail():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, ParseRun, ResumeFile, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="mrg-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="mrg-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        primary = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                            structured_data={"city": "杭州"}, search_text="杭州")
        absorbed = Candidate(workspace_id=ws.id, status=CandidateStatus.pending_review, name="张三",
                             structured_data={"skills": ["Java"]}, search_text="Java")
        db.add_all([primary, absorbed])
        await db.flush()
        base = primary.latest_revision_id
        run = ParseRun(run_id="mrg-run", workspace_id=ws.id, upload_id="u1", source_channel="referral",
                       referrer="李四", format="pdf", file_hash="f1", file_path="p1", file_size=1,
                       parser_version="v1")
        db.add(run)
        await db.flush()
        db.add(ResumeFile(run_id="mrg-run", candidate_id=primary.id, file_hash="f1", storage_key="k1",
                          format="pdf", file_size=1, content_type="application/pdf"))
        await db.commit()
        ws_id, p_id, a_id = ws.id, primary.id, absorbed.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "mrg-owner@example.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "mrg-owner@example.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        # 详情内推归属
        r = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{p_id}", headers=h)
        assert r.status_code == 200
        assert r.json()["source_channel"] == "referral"
        assert r.json()["referrer"] == "李四"
        # 合并
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{p_id}/merge", headers=h,
                         json={"duplicate_id": a_id, "base_revision_id": base})
        assert r.status_code == 200
        assert r.json()["status"] == "merged"
        # 被并入者已软删
        r2 = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{a_id}", headers=h)
        assert r2.status_code == 404


@pytest.mark.asyncio
async def test_merge_conflict_api_409():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="mrg2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="mrg2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        primary = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                            structured_data={}, search_text="")
        absorbed = Candidate(workspace_id=ws.id, status=CandidateStatus.pending_review, name="张三",
                             structured_data={}, search_text="")
        db.add_all([primary, absorbed])
        await db.commit()
        ws_id, p_id, a_id = ws.id, primary.id, absorbed.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "mrg2-owner@example.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "mrg2-owner@example.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{p_id}/merge", headers=h,
                         json={"duplicate_id": a_id, "base_revision_id": 999})
        assert r.status_code == 409
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_candidates_api.py::test_merge_candidates_api_and_referrer_detail backend/tests/test_candidates_api.py::test_merge_conflict_api_409 -v`
预期：FAIL（merge 端点 404 / 详情缺字段）

- [x] **步骤 3：实现合并端点 + 详情内推归属**

`backend/app/api/candidates.py`：

(1) 详情 `get_candidate` 返回前补来源渠道与内推人：

```python
    from app.models import ParseRun
    source_channel = referrer = None
    if rf:
        run = (await db.execute(select(ParseRun).where(ParseRun.run_id == rf.run_id))).scalar_one_or_none()
        if run is not None:
            source_channel, referrer = run.source_channel, run.referrer
    return {"candidate": view, "ir": ir, "suitable_jobs": suitable_jobs,
            "source_channel": source_channel, "referrer": referrer}
```

(2) 新增合并端点：

```python
class MergeRequest(BaseModel):
    duplicate_id: int
    base_revision_id: int


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/merge")
async def merge_candidate(ws_id: int, candidate_id: int, body: MergeRequest,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.candidate_merge import MergeConflictError, MergeError, merge_candidates
    from app.services.audit import add_event

    primary = await _visible_candidate(db, ws_id, candidate_id, user)
    absorbed = await _visible_candidate(db, ws_id, body.duplicate_id, user)
    try:
        await merge_candidates(db, primary=primary, absorbed=absorbed,
                               base_revision_id=body.base_revision_id, actor_id=user.id)
    except MergeConflictError as exc:
        raise HTTPException(409, str(exc))
    except MergeError as exc:
        raise HTTPException(400, str(exc))
    await add_event(db, action="candidate.merged", result="success", resource_type="candidate",
                    resource_id=str(primary.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"absorbed_id": absorbed.id})
    await db.commit()
    return {"candidate_id": primary.id, "absorbed_id": absorbed.id, "status": "merged"}
```

- [x] **步骤 4：列表 referrer 筛选**

`backend/app/services/candidate_list.py` 的 `list_candidates` 增加 `referrer: str | None = None` 形参，在 `source_channel` 分支后追加：

```python
    if referrer:
        sub = select(ResumeFile.id).join(ParseRun, ParseRun.run_id == ResumeFile.run_id) \
            .where(ResumeFile.candidate_id == c.id, ParseRun.referrer == referrer)
        base = base.where(exists(sub))
```

`backend/app/api/candidates.py` 的 `list_candidates` 增加 `referrer: str | None = None` 查询参数并透传。

- [x] **步骤 5：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_candidates_api.py -v`
预期：PASS

- [x] **步骤 6：Commit**

```bash
git add backend/app/api/candidates.py backend/app/services/candidate_list.py backend/tests/test_candidates_api.py
git commit -m "feat: add candidate merge endpoint and referral attribution (P6 F12)"
```

---

### 任务 3：前端合并入口 + 内推归属展示

**文件：**
- 修改：`frontend/src/api/candidates.ts`
- 修改：`frontend/src/pages/CandidatesPage.tsx`
- 修改：`frontend/src/pages/CandidateDetailPage.tsx`

- [x] **步骤 1：API 客户端加 mergeCandidates**

`frontend/src/api/candidates.ts` 追加：

```ts
export async function mergeCandidates(wsId: number, id: number, duplicateId: number, baseRevisionId: number) {
  return client.post(`/workspaces/${wsId}/candidates/${id}/merge`, { duplicate_id: duplicateId, base_revision_id: baseRevisionId }).then((r) => r.data);
}
```

- [x] **步骤 2：列表页加 referrer 筛选**

`frontend/src/pages/CandidatesPage.tsx`：筛选区加 referrer 输入，`listCandidates` 透传 `referrer`。

- [x] **步骤 3：详情页来源/内推人 + 合并入口**

`frontend/src/pages/CandidateDetailPage.tsx`：状态行下方展示 `来源渠道`/`内推人`；新增「合并候选人」区块（输入被合并候选人 ID + 按钮，调用 `mergeCandidates`，成功后刷新并提示）。

- [x] **步骤 4：构建与测试**

```bash
cd frontend && npm install && npm run build && npx vitest run
```

预期：通过

- [x] **步骤 5：Commit**

```bash
git add frontend/src/api/candidates.ts frontend/src/pages/CandidatesPage.tsx frontend/src/pages/CandidateDetailPage.tsx
git commit -m "feat: add merge UI and referral attribution display (P6 F12)"
```

---

### 任务 4：回归验证与台账

- [x] **步骤 1：全量回归**

```bash
export MODEL_KEY_ENC_KEY="..." && export JWT_SECRET="..." && export DATABASE_URL="..."
../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests -q
```

预期：全量通过（main 236 + P6 新增全部）

- [x] **步骤 2：静态检查**

```bash
../.worktrees/p2-resume-parsing/.venv/bin/ruff check backend/app backend/tests && git diff --check
```

- [x] **步骤 3：更新台账**

在 `docs/superpowers/deviation-log.md` 追加 §14「P6 查重合并与内推归属（F12 剩余）实现与偏离」，记录 N-1~N-6 裁决与验证。

- [x] **步骤 4：勾选计划并提交**

```bash
git add -A && git commit -m "docs: 记录 P6 查重合并与内推归属实现偏差与验证（P6 F12）"
```

---

## 自检

**1. 规格覆盖度：**

| 需求 | 对应任务 |
|------|---------|
| 查重合并动作（最新解析值 + override 优先，保留全部文件/历史） | 任务 1、2 |
| 合并权限（member+，hired/deleted 拒绝，乐观锁 409） | 任务 2 |
| 合并留痕（merged 事件 + 审计） | 任务 1、2 |
| 内推归属展示（详情 source_channel/referrer） | 任务 2、3 |
| 列表 referrer 筛选 | 任务 2、3 |
| 前端合并入口 + 内推人展示 | 任务 3 |

**2. 占位符扫描：** 无 TODO/占位；`merge_candidates` 签名在任务 1 定义、任务 2 消费一致；`_visible_candidate`（P4 已有）在任务 2 复用。

**3. 类型一致性：** `CandidateEventType.merged` 在任务 1 定义、append/查询一致；`list_candidates` 新增 `referrer` 形参在 service/API 一致；详情响应新增字段在任务 2 定义、任务 3 前端消费一致。

**已知边界（后续处理）：** 模糊查重（向量相似度，P1 预留）；合并后被并入者恢复为独立候选人（数据以主体副本为准）；重新解析（F8 re-parse）与并发；F13 指派管道。