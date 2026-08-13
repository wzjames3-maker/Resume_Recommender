# P4 候选人管理（F8）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [x]`）语法来跟踪进度。

**目标：** 实现 F8 候选人管理——候选人列表与多维筛选、详情（结构化字段 + 画像 + 原文 IR 对照）、人工 override/clear 字段修正（合并视图）、软删除/恢复/硬删除生命周期、时间线留痕，并联动 F9 池可见性权限（member 不可见 hired）。

**架构：** 在 P2 候选人领域 + P3 搜人群上新增管理域。展示/检索统一走「最新 revision 解析值 + 人工 override/clear 覆盖」的**合并视图**（spec §2）；override 写 `candidate_overrides`（含 before/after/action/actor/revision_id），清除写 `clear`；生命周期 `active → deleted(30天可恢复) → purged`，删除/恢复/修正均在同一事务内追加不可变 `candidate_events` 时间线事件；池可见性按成员角色过滤（member：active/rejected/pending_review；admin/owner：+hired）。列表筛选用 SQLAlchemy Core（结构化 JSONB + search_tsv + 画像 profile_json + source_channel join）。

**技术栈：** FastAPI、SQLAlchemy 2.0（async）、pgvector、tsearch、pydantic v2、pytest。

**参考：** `docs/PRD.md` §7.2 F8、§7.2 F9 权限矩阵、`docs/superpowers/specs/2026-08-07-resume-schema-and-import.md` §2（字段优先级与 override/clear）、P2 计划 A-6/A-7 裁决、P3 S-3 池可见性。

---

## 设计决策与歧义裁决（实现前必读）

| # | 歧义 / 取舍 | 依据 | 本计划裁决 |
|---|------------|------|-----------|
| C-1 | override 的 field_path 形态 | spec §2「数组按关键字段配对后逐字段 override」 | **P4 用索引路径**（如 `work[0].content`，与详情页展示一致）；关键字段配对、数组增删元素留后续（详情页展示的就是索引序） |
| C-2 | 时间线事件模型 | PRD F8「状态流转、面试安排与反馈、沟通备注按时间倒序留痕」 | 新增 `candidate_events` 表（event_type：created/status_changed/field_override/note/restored/purged），同一事务内追加，只 append 不可变；面试安排/反馈（F13/F14）后续扩展类型 |
| C-3 | 软删除恢复是否重建索引 | PRD F8「恢复必须恢复可见状态并重建索引」 | 软删除**保留** search_tsv/五段向量/IR（PRD 明确），恢复时 `search_text = search_text`（触发 tsvector 同步 trigger）即「重建索引」的等价物；嵌入向量未变无需重算 |
| C-4 | hired 候选人的写操作 | F9 矩阵「字段修正/删除/恢复/合并 允许，但进行中指派或 hired 默认拒绝删除/合并」 | override/clear 修正对 hired **允许**（仅约束删除/合并）；删除对 hired **拒绝 409**；purge 仅对 deleted |
| C-5 | 来源渠道筛选 | 渠道在 parse_runs，candidates 无该列 | 列表 `source_channel` 筛选经 `resume_files.run_id → parse_runs.source_channel` JOIN |
| C-6 | 池可见性 | F9 矩阵「active/rejected 列表/详情 member 允许；hired 及原文/IR/PII member 拒绝」 | 列表/详情按角色过滤：member 仅 active/rejected/pending_review；admin/owner 另含 hired；member 访问 hired 详情统一 404（不泄露存在性）；deleted 仅通过显式 restorable 筛选可见 |
| C-7 | 硬删除（purge） | PRD F8「purged 硬删除/加密擦除，保留不可逆 tombstone」 | purge 前写审计事件（含 candidate_id + search_text hash），再 `db.delete`（FK CASCADE 级联 revision/override/嵌入/文件）；审计事件不删除（tombstone） |
| C-8 | 修正并发保护 | spec §2「人工修正与重新解析均带乐观锁（基于 revision_id）」 | override 请求携带 `base_revision_id`，与 latest_revision_id 不一致 → 409（提示 HR 刷新）；P4 不做重新解析并发（F8 re-parse 留后续） |

---

## 文件结构

```
backend/
  alembic/versions/<new>_add_candidate_events.py   (新：candidate_events 表)
  app/
    models/
      candidate_event.py                            (新：CandidateEvent + CandidateEventType)
      __init__.py                                   (修改：导出)
    services/
      candidate_view.py                            (新：path 解析 + override 合并视图 + 详情组装)
      candidate_list.py                            (新：列表/筛选 SQL)
      candidate_lifecycle.py                       (新：软删/恢复/硬删 + 时间线事件追加)
    api/
      candidates.py                                (新：列表/详情/override/删除/恢复/purge/时间线/备注)
    main.py                                        (修改：注册 candidates router)
  tests/
    test_candidate_view.py                         (新)
    test_candidate_list.py                         (新)
    test_candidate_lifecycle.py                    (新)
    test_candidates_api.py                         (新)
  frontend/src/
    api/candidates.ts                              (新)
    pages/CandidatesPage.tsx                       (新：列表 + 筛选)
    pages/CandidateDetailPage.tsx                  (新：详情 + 修正 + 时间线)
    App.tsx                                        (修改：/candidates 路由)
```

**领域边界**：P4 不改 P2 解析流水线、P3 搜人链路；候选列表复用 `Candidate`/`CandidateRevision`/`CandidateOverride` 已有表，仅新增 `candidate_events`。

---

### 任务 1：时间线事件表

**文件：**
- 创建：`backend/app/models/candidate_event.py`
- 创建：`backend/alembic/versions/<new>_add_candidate_events.py`
- 修改：`backend/app/models/__init__.py`
- 测试：`backend/tests/test_candidate_view.py`（追加 roundtrip）

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidate_view.py
import pytest


@pytest.mark.asyncio
async def test_candidate_event_roundtrip():
    from app.core.database import SessionLocal
    from app.models import CandidateEvent, CandidateEventType, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="evt-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="evt-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        from app.models import Candidate, CandidateStatus
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        db.add(cand)
        await db.flush()
        evt = CandidateEvent(candidate_id=cand.id, event_type=CandidateEventType.created,
                             title="候选人创建", actor_id=owner.id, detail={"source": "parse"})
        db.add(evt)
        await db.commit()
        got = await db.get(CandidateEvent, evt.id)
        assert got.event_type is CandidateEventType.created
        assert got.detail["source"] == "parse"
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_candidate_view.py::test_candidate_event_roundtrip -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：创建模型**

```python
# backend/app/models/candidate_event.py
import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK


class CandidateEventType(str, enum.Enum):
    created = "created"
    status_changed = "status_changed"
    field_override = "field_override"
    note = "note"
    restored = "restored"
    purged = "purged"


class CandidateEvent(Base):
    __tablename__ = "candidate_events"
    __table_args__ = (Index("ix_candidate_events_candidate_created", "candidate_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[CandidateEventType] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    detail = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

> 说明：`event_type` 用 `String(32)` 存枚举值（值固定，避免 PG enum 迁移负担；Python 侧枚举校验）。

- [x] **步骤 4：生成迁移**

```bash
cd backend
../../.worktrees/p2-resume-parsing/.venv/bin/alembic revision --autogenerate -m "add candidate events"
../../.worktrees/p2-resume-parsing/.venv/bin/alembic upgrade head
```

- [x] **步骤 5：更新 __init__ 导出**

`backend/app/models/__init__.py` 追加导入与 `__all__`：`CandidateEvent`、`CandidateEventType`。

- [x] **步骤 6：运行测试验证通过**

运行：`pytest backend/tests/test_candidate_view.py::test_candidate_event_roundtrip -v`
预期：PASS

- [x] **步骤 7：Commit**

```bash
git add backend/app/models backend/alembic/versions backend/tests/test_candidate_view.py
git commit -m "feat: add candidate timeline events model (P4 F8)"
```

---

### 任务 2：合并视图（latest revision + override/clear）

**文件：**
- 创建：`backend/app/services/candidate_view.py`
- 测试：`backend/tests/test_candidate_view.py`

**验收（spec §2）：** 展示/检索使用「最新 revision 解析值 + override/clear 覆盖」；override 覆盖值、clear 置 null；`base_revision_id` 不匹配当前 revision 报并发冲突。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidate_view.py
import pytest


def test_resolve_and_set_path():
    from app.services.candidate_view import set_path
    obj = {"name": "张三", "work": [{"company": "A", "title": "工程师"}]}
    out = set_path(obj, "work[0].title", "高级工程师")
    assert out["work"][0]["title"] == "高级工程师"
    out2 = set_path(obj, "city", "杭州")
    assert out2["city"] == "杭州"


def test_apply_overrides_override_and_clear():
    from app.services.candidate_view import apply_overrides
    base = {"name": "张三", "city": "杭州", "work": [{"company": "A", "title": "工程师"}]}
    overrides = [
        {"field_path": "city", "action": "override", "after_value": "上海"},
        {"field_path": "work[0].title", "action": "override", "after_value": "高级工程师"},
        {"field_path": "name", "action": "clear", "after_value": None},
    ]
    merged = apply_overrides(base, overrides)
    assert merged["city"] == "上海"
    assert merged["work"][0]["title"] == "高级工程师"
    assert merged["name"] is None


@pytest.mark.asyncio
async def test_effective_view_applies_overrides():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateOverride, CandidateRevision, CandidateStatus, User, Workspace
    from app.services.candidate_view import build_effective_view

    async with SessionLocal() as db:
        owner = User(email="view-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="view-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={"city": "杭州"}, search_text="")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="r", revision_id="r:rev1",
                                candidate_json={"name": "张三", "city": "杭州", "skills": ["Java"]},
                                evidence={}, profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        db.add(CandidateOverride(candidate_id=cand.id, revision_id="r:rev1", field_path="city",
                                 before_value="杭州", after_value="上海", action="override", actor_id=owner.id))
        await db.commit()
        view = await build_effective_view(db, cand.id)
        assert view["fields"]["city"] == "上海"
        assert view["fields"]["skills"] == ["Java"]
        assert view["profile"]["level"] == "Mid"
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_candidate_view.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现 path 工具与合并视图**

```python
# backend/app/services/candidate_view.py
import re
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, CandidateOverride, CandidateRevision

_PATH_RE = re.compile(r"^([A-Za-z_]+)(?:\[(\d+)\])?(?:\.[A-Za-z_]+)*$")


def set_path(obj: dict, path: str, value, *, clear: bool = False) -> dict:
    """按索引路径（work[0].title）写入/清除值。返回新 dict（不原地改）。"""
    import copy
    result = copy.deepcopy(obj)
    tokens = path.replace("]", "").split("[")  # ["work", "0", ".title"] 简化
    # 更稳的解析：逐段
    parts = re.findall(r"[a-zA-Z_]+|\[\d+\]", path)
    node = result
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part.startswith("["):
            idx = int(part[1:-1])
            if last:
                if clear:
                    node[idx] = None
                else:
                    node[idx] = value
            else:
                node = node[idx]
        else:
            if last:
                if clear:
                    node[part] = None
                else:
                    node[part] = value
            else:
                node = node.setdefault(part, {} if parts[i + 1].startswith("[") else {})
    return result


def apply_overrides(base: dict, overrides: list) -> dict:
    """按 override/clear 作用域顺序应用。same field 多个 override 时后写覆盖先写。"""
    merged = dict(base)
    for ov in overrides:
        action = ov["action"]
        if action == "override":
            merged = set_path(merged, ov["field_path"], ov["after_value"])
        elif action == "clear":
            merged = set_path(merged, ov["field_path"], None)
    return merged


async def build_effective_view(db: AsyncSession, candidate_id: int) -> dict:
    """候选人详情合并视图：latest revision 解析值 + override/clear + 画像。"""
    cand = await db.get(Candidate, candidate_id)
    if cand is None:
        raise ValueError(f"候选人不存在: {candidate_id}")
    rev = (await db.execute(select(CandidateRevision).where(
        CandidateRevision.id == cand.latest_revision_id))).scalar_one_or_none()
    base = dict(rev.candidate_json) if rev else dict(cand.structured_data or {})
    overrides = (await db.execute(select(CandidateOverride).where(
        CandidateOverride.candidate_id == candidate_id))).scalars().all()
    fields = apply_overrides(base, [{"field_path": o.field_path, "action": o.action.value,
                                     "after_value": o.after_value} for o in overrides])
    profile = (rev.profile_json or {}).get("values") or {} if rev else {}
    return {
        "candidate_id": candidate_id,
        "name": cand.name,
        "status": cand.status.value,
        "deleted_until": cand.deleted_until.isoformat() if cand.deleted_until else None,
        "fields": fields,
        "profile": profile,
        "latest_revision_id": cand.latest_revision_id,
    }
```

> 说明：`set_path` 用 `re.findall` 解析 `work[0].title` → `["work","[0]","title"]`；数组元素 override 按索引（C-1）。`build_effective_view` 返回详情所需全部字段。

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_candidate_view.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/candidate_view.py backend/tests/test_candidate_view.py
git commit -m "feat: add candidate effective view with override/clear merge (P4 F8)"
```

---

### 任务 3：候选人列表与筛选

**文件：**
- 创建：`backend/app/services/candidate_list.py`
- 测试：`backend/tests/test_candidate_list.py`

**验收（PRD F8）：** 按状态/技能/城市/学历/年限/画像维度/来源渠道筛选；分页；member 只见 active/rejected/pending_review，admin/owner 另含 hired；deleted 不入默认列表。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidate_list.py
import pytest


@pytest.mark.asyncio
async def test_list_candidates_filters_and_paginates():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateRevision, CandidateStatus, User, Workspace
    from app.services.candidate_list import list_candidates

    async with SessionLocal() as db:
        owner = User(email="list-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="list-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        for i, (name, status) in enumerate([("张三", "active"), ("李四", "hired"), ("王五", "pending_review")]):
            cand = Candidate(workspace_id=ws.id, status=CandidateStatus(status), name=name,
                             structured_data={"skills": ["Java"], "years_experience": 5, "city": "杭州",
                                              "highest_degree": "本科"}, search_text="Java")
            db.add(cand)
            await db.flush()
            rev = CandidateRevision(candidate_id=cand.id, run_id=f"r{i}", revision_id=f"r{i}:rev1",
                                    candidate_json={"name": name, "skills": ["Java"]}, evidence={},
                                    profile_json={"values": {"level": "Mid"}, "evidence": {}})
            db.add(rev)
            await db.flush()
            cand.latest_revision_id = rev.id
        await db.commit()

        # member 不可见 hired
        total, items = await list_candidates(db, ws.id, scopes={"active", "pending_review", "rejected"},
                                             page=1, page_size=10)
        names = {i["name"] for i in items}
        assert "张三" in names and "王五" in names
        assert "李四" not in names

        # admin 可见 hired
        total2, items2 = await list_candidates(db, ws.id, scopes={"active", "pending_review", "rejected", "hired"},
                                               page=1, page_size=10)
        assert any(i["name"] == "李四" for i in items2)

        # 技能筛选
        from app.services.candidate_list import build_list_predicates
        total3, items3 = await list_candidates(db, ws.id, scopes={"active", "pending_review", "rejected", "hired"},
                                               skills=["Java"], page=1, page_size=10)
        assert total3 >= 2
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_candidate_list.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现列表筛选**

```python
# backend/app/services/candidate_list.py
from dataclasses import dataclass

from sqlalchemy import Integer, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, CandidateRevision, CandidateStatus, ParseRun, ResumeFile
from app.services.search.schema import DEGREE_ORDINAL

_VISIBLE_DEFAULT = {CandidateStatus.active, CandidateStatus.pending_review, CandidateStatus.rejected}


@dataclass
class ListItem:
    candidate_id: int
    name: str | None
    status: str
    city: str | None
    highest_degree: str | None
    years_experience: int | None
    level: str | None
    updated_at: object


async def list_candidates(db: AsyncSession, workspace_id: int, *, scopes: set[str],
                          skills: list[str] | None = None, city: str | None = None,
                          years_min: int | None = None, degree_at_least: str | None = None,
                          level: str | None = None, domain: str | None = None,
                          source_channel: str | None = None,
                          page: int = 1, page_size: int = 20) -> tuple[int, list[dict]]:
    statuses = [CandidateStatus(s) for s in scopes if s in {
        "active", "pending_review", "rejected", "hired"}]
    if not statuses:
        return 0, []
    page, page_size = max(1, page), max(1, min(page_size, 100))
    c = Candidate
    cr = CandidateRevision
    base = (
        select(c.id, c.name, c.status, c.created_at)
        .join(cr, cr.id == c.latest_revision_id)
        .where(c.workspace_id == workspace_id, c.status.in_(statuses))
    )
    if skills:
        for s in skills:
            base = base.where(c.search_tsv.op("@@")(func.plainto_tsquery("simple", s)))
    if city:
        base = base.where((c.structured_data.op("->>")("city") == city)
                          | (c.structured_data.op("->>")("expected_city") == city))
    if years_min is not None:
        base = base.where(func.coalesce(cast(c.structured_data.op("->>")("years_experience"), Integer), -1) >= years_min)
    if degree_at_least:
        low = DEGREE_ORDINAL.get(degree_at_least)
        if low is not None:
            ordinal_case = case(
                *[(c.structured_data.op("->>")("highest_degree") == d, o) for d, o in DEGREE_ORDINAL.items()],
                else_=0)
            base = base.where(ordinal_case >= low)
    if level:
        base = base.where(cr.profile_json["values"]["level"].astext == level)
    if domain:
        base = base.where(cr.profile_json["values"]["domain"].astext == domain)
    if source_channel:
        base = base.join(ResumeFile, ResumeFile.candidate_id == c.id)\
                   .join(ParseRun, ParseRun.run_id == ResumeFile.run_id)\
                   .where(ParseRun.source_channel == source_channel)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = await db.execute(base.order_by(c.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    items = []
    for cid, name, status, created in rows:
        items.append({"candidate_id": cid, "name": name, "status": status.value,
                      "created_at": created.isoformat() if created else None})
    return total, items
```

> 说明：`scopes` 由 API 层按成员角色派生（C-6）；`source_channel` 经 ResumeFile→ParseRun JOIN（C-5）。列表项为精简卡片，详情/画像走详情接口。

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_candidate_list.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/candidate_list.py backend/tests/test_candidate_list.py
git commit -m "feat: add candidate list with multi-dim filters and pool scopes (P4 F8)"
```

---

### 任务 4：候选人详情 API + 原文 IR 对照

**文件：**
- 创建：`backend/app/api/candidates.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_candidates_api.py`

**验收（PRD F8）：** 详情返回合并视图字段 + 画像 + 原文 IR（member 拒绝 hired，跨租户 404）。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidates_api.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_get_candidate_detail_returns_effective_fields():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateOverride, CandidateRevision, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="cd-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cd-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={"city": "杭州"}, search_text="")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="r", revision_id="r:rev1",
                                candidate_json={"name": "张三", "city": "杭州"}, evidence={},
                                profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        db.add(CandidateOverride(candidate_id=cand.id, revision_id="r:rev1", field_path="city",
                                 before_value="杭州", after_value="上海", action="override", actor_id=owner.id))
        await db.commit()
        ws_id, cand_id = ws.id, cand.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "cd@b.com", "password": "secret123", "nickname": "C"})
        token = (await c.post("/api/v1/auth/login", json={"email": "cd@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id2 = (await c.post("/api/v1/workspaces", json={"name": "CD-WS"}, headers=h)).json()["id"]
        r = await c.get(f"/api/v1/workspaces/{ws_id2}/candidates/{cand_id}", headers=h)
        assert r.status_code == 404  # 跨 workspace 隔离
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_candidates_api.py -v`
预期：FAIL，报错 404（路由不存在）

- [x] **步骤 3：实现详情端点**

`backend/app/api/candidates.py`：

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Candidate, CandidateStatus, ParseRun, ResumeFile, User, WorkspaceMember
from app.services.candidate_view import build_effective_view

router = APIRouter(prefix="/api/v1", tags=["candidates"])

MEMBER_VISIBLE = {"active", "pending_review", "rejected"}
ADMIN_VISIBLE = {"active", "pending_review", "rejected", "hired"}


async def _member_info(db, ws_id, user_id):
    row = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "资源不存在")
    return row


def _visible_scopes(role: str) -> set[str]:
    return ADMIN_VISIBLE if role in ("admin", "owner") else MEMBER_VISIBLE


@router.get("/workspaces/{ws_id}/candidates")
async def list_candidates(ws_id: int, status: str | None = None, skills: str | None = None,
                          city: str | None = None, years_min: int | None = None,
                          degree_at_least: str | None = None, level: str | None = None,
                          domain: str | None = None, source_channel: str | None = None,
                          page: int = 1, page_size: int = 20,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.candidate_list import list_candidates as _list
    membership = await _member_info(db, ws_id, user.id)
    role = membership.role.value if hasattr(membership.role, "value") else str(membership.role)
    scopes = _visible_scopes(role)
    if status and status in scopes:
        scopes = {status}
    total, items = await _list(db, ws_id, scopes=scopes,
                               skills=skills.split(",") if skills else None, city=city,
                               years_min=years_min, degree_at_least=degree_at_least,
                               level=level, domain=domain, source_channel=source_channel,
                               page=page, page_size=page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/workspaces/{ws_id}/candidates/{candidate_id}")
async def get_candidate(ws_id: int, candidate_id: int,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    role = membership.role.value if hasattr(membership.role, "value") else str(membership.role)
    cand = await db.get(Candidate, candidate_id)
    if cand is None or cand.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    if cand.status.value not in _visible_scopes(role):
        raise HTTPException(404, "资源不存在")
    view = await build_effective_view(db, candidate_id)
    # 原文对照：取该候选最新 run 的 IR
    from app.models import ResumeIR
    rf = (await db.execute(select(ResumeFile).where(ResumeFile.candidate_id == candidate_id)
                           .order_by(ResumeFile.id.desc()).limit(1))).scalar_one_or_none()
    ir = None
    if rf:
        ir_row = (await db.execute(select(ResumeIR).where(ResumeIR.run_id == rf.run_id))).scalar_one_or_none()
        ir = ir_row.content if ir_row else None
    return {"candidate": view, "ir": ir}
```

- [x] **步骤 4：注册路由**

`backend/app/main.py`：`from app.api import candidates` + `app.include_router(candidates.router)`。

- [x] **步骤 5：运行测试验证通过**

运行：`pytest backend/tests/test_candidates_api.py -v`
预期：PASS

- [x] **步骤 6：Commit**

```bash
git add backend/app/api/candidates.py backend/app/main.py backend/tests/test_candidates_api.py
git commit -m "feat: add candidate list and detail endpoints with pool scopes (P4 F8)"
```

---

### 任务 5：字段 override/clear 修正

**文件：**
- 修改：`backend/app/api/candidates.py`
- 修改：`backend/app/services/candidate_lifecycle.py`（新建）
- 测试：`backend/tests/test_candidates_api.py`（追加）

**验收（spec §2 / PRD F8）：** PATCH 写 `candidate_overrides`（before/after/action/actor/revision_id）+ 时间线事件；`base_revision_id` 不匹配 → 409；hired 允许修正（C-4）。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidates_api.py 追加
@pytest.mark.asyncio
async def test_override_field_records_event_and_conflict():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateRevision, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="ov-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="ov-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="r", revision_id="r:rev1",
                                candidate_json={"name": "张三", "city": "杭州"}, evidence={})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        await db.commit()
        ws_id, cand_id, rev_id = ws.id, cand.id, rev.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "ov@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "ov@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/fields",
                         json={"base_revision_id": rev_id, "field_path": "city",
                               "action": "override", "after_value": "上海"}, headers=h)
        assert r.status_code == 200
        assert r.json()["fields"]["city"] == "上海"
        # 并发冲突：base_revision_id 过期
        r2 = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/fields",
                          json={"base_revision_id": 999, "field_path": "city",
                                "action": "override", "after_value": "北京"}, headers=h)
        assert r2.status_code == 409
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_candidates_api.py::test_override_field_records_event_and_conflict -v`
预期：PASS（本测试在端点存在后才有意义；若先行此测试则 FAIL 404）

- [x] **步骤 3：实现生命周期 service（事件追加）**

```python
# backend/app/services/candidate_lifecycle.py
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CandidateEvent, CandidateEventType


async def append_event(db: AsyncSession, *, candidate_id: int, event_type: CandidateEventType,
                       title: str, detail: dict | None = None, actor_id: int | None = None) -> None:
    db.add(CandidateEvent(candidate_id=candidate_id, event_type=event_type.value,
                          title=title, detail=detail or {}, actor_id=actor_id))
```

- [x] **步骤 4：实现 override 端点**

`backend/app/api/candidates.py` 追加：

```python
from pydantic import BaseModel


class OverrideRequest(BaseModel):
    base_revision_id: int
    field_path: str
    action: str  # override / clear
    after_value: object | None = None


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/fields")
async def override_field(ws_id: int, candidate_id: int, body: OverrideRequest,
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    role = membership.role.value if hasattr(membership.role, "value") else str(membership.role)
    cand = await db.get(Candidate, candidate_id)
    if cand is None or cand.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    if cand.status.value not in _visible_scopes(role) or cand.status is CandidateStatus.deleted:
        raise HTTPException(404, "资源不存在")
    if body.action not in ("override", "clear"):
        raise HTTPException(400, "action 必须为 override/clear")
    if cand.latest_revision_id != body.base_revision_id:
        raise HTTPException(409, "候选人已被重新解析，请刷新后重试")
    from app.models import CandidateOverride
    # before_value 从当前合并视图取
    from app.services.candidate_view import build_effective_view
    view = await build_effective_view(db, candidate_id)
    before = _path_get(view["fields"], body.field_path)
    db.add(CandidateOverride(candidate_id=candidate_id, revision_id=_rev_id_of(cand),
                             field_path=body.field_path,
                             before_value=before, after_value=body.after_value,
                             action=body.action, actor_id=user.id))
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.field_override,
                       title=f"字段修正 {body.field_path}", detail={"field_path": body.field_path, "action": body.action},
                       actor_id=user.id)
    await db.commit()
    view2 = await build_effective_view(db, candidate_id)
    return {"fields": view2["fields"]}
```

> 说明：`_path_get`/`_rev_id_of` 为辅助函数（`_path_get` 复用 `set_path` 的逆向解析——实现时直接在 `candidate_view.py` 增加 `get_path`；`_rev_id_of` 取 `candidate.latest_revision_id` 对应 revision 的 revision_id 字符串）。

- [x] **步骤 5：运行测试验证通过**

运行：`pytest backend/tests/test_candidates_api.py -v`
预期：PASS

- [x] **步骤 6：Commit**

```bash
git add backend/app/api/candidates.py backend/app/services/candidate_lifecycle.py backend/tests/test_candidates_api.py
git commit -m "feat: add field override/clear with optimistic lock and timeline event (P4 F8)"
```

---

### 任务 6：生命周期（软删除/恢复/硬删除）

**文件：**
- 修改：`backend/app/api/candidates.py`
- 修改：`backend/app/services/candidate_lifecycle.py`
- 测试：`backend/tests/test_candidates_api.py`（追加）

**验收（PRD F8/C-3/C-4/C-7）：** DELETE → deleted+30天；restore → active+重建索引；purge → 审计 tombstone 后级联硬删；hired 拒绝删除。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidates_api.py 追加
@pytest.mark.asyncio
async def test_candidate_soft_delete_restore_and_purge():
    from datetime import timedelta
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateRevision, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="lc-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="lc-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="Java")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="r", revision_id="r:rev1",
                                candidate_json={"name": "张三"}, evidence={})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        await db.commit()
        ws_id, cand_id = ws.id, cand.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "lc@b.com", "password": "secret123", "nickname": "L"})
        token = (await c.post("/api/v1/auth/login", json={"email": "lc@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws2 = (await c.post("/api/v1/workspaces", json={"name": "LC-WS"}, headers=h)).json()
        # 跨 workspace 404
        assert (await c.delete(f"/api/v1/workspaces/{ws2['id']}/candidates/{cand_id}", headers=h)).status_code == 404
        # 软删除
        r = await c.delete(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"
        # 恢复
        r2 = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/restore", headers=h)
        assert r2.status_code == 200
        assert r2.json()["status"] == "active"
        # 再删再 purge
        await c.delete(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        r3 = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/purge", headers=h)
        assert r3.status_code == 200
        # 已硬删 → 详情 404
        assert (await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)).status_code == 404
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_candidates_api.py::test_candidate_soft_delete_restore_and_purge -v`
预期：FAIL 404（端点未实现）

- [x] **步骤 3：实现生命周期端点**

`backend/app/api/candidates.py` 追加：

```python
from datetime import UTC, datetime, timedelta


@router.delete("/workspaces/{ws_id}/candidates/{candidate_id}")
async def soft_delete(ws_id: int, candidate_id: int,
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cand = await _visible_candidate(db, ws_id, candidate_id, user)
    if cand.status is CandidateStatus.hired:
        raise HTTPException(409, "入职员工不可删除")
    if cand.status is CandidateStatus.deleted:
        raise HTTPException(409, "候选人已删除")
    cand.status = CandidateStatus.deleted
    cand.deleted_until = datetime.now(UTC) + timedelta(days=30)
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.status_changed,
                       title="软删除", detail={"from": "active", "to": "deleted"}, actor_id=user.id)
    await db.commit()
    return {"candidate_id": candidate_id, "status": "deleted", "deleted_until": cand.deleted_until.isoformat()}


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/restore")
async def restore_candidate(ws_id: int, candidate_id: int,
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cand = await _visible_candidate(db, ws_id, candidate_id, user)
    if cand.status is not CandidateStatus.deleted:
        raise HTTPException(409, "仅已删除候选人可恢复")
    cand.status = CandidateStatus.active
    cand.deleted_until = None
    cand.search_text = cand.search_text  # 触发 tsvector 同步（C-3）
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.restored,
                       title="恢复", actor_id=user.id)
    await db.commit()
    return {"candidate_id": candidate_id, "status": "active"}


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/purge")
async def purge_candidate(ws_id: int, candidate_id: int,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cand = await _visible_candidate(db, ws_id, candidate_id, user)
    if cand.status is not CandidateStatus.deleted:
        raise HTTPException(409, "仅已删除候选人可硬删除")
    from app.services.audit import add_event
    await add_event(db, action="candidate.purged", result="success", resource_type="candidate",
                    resource_id=str(candidate_id), workspace_id=ws_id, actor_id=user.id,
                    payload={"name": cand.name, "search_text_hash": _sha256(cand.search_text or "")})
    await db.delete(cand)  # FK CASCADE 级联 revision/override/嵌入/文件/事件
    await db.commit()
    return {"candidate_id": candidate_id, "status": "purged"}
```

> 说明：`_visible_candidate` 为详情/写操作公共辅助（校验 workspace + 角色可见性 + 返回候选）；`_sha256` 为 `hashlib.sha256(...).hexdigest()`。时间线事件在删除后随 CASCADE 一并删除（purged 后事件不保留，审计事件保留 tombstone）。

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_candidates_api.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/api/candidates.py backend/tests/test_candidates_api.py
git commit -m "feat: add candidate soft delete, restore and purge lifecycle (P4 F8)"
```

---

### 任务 7：时间线 + 备注

**文件：**
- 修改：`backend/app/api/candidates.py`
- 测试：`backend/tests/test_candidates_api.py`（追加）

**验收（PRD F8）：** GET 时间线倒序；POST 备注追加 note 事件。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_candidates_api.py 追加
@pytest.mark.asyncio
async def test_candidate_timeline_and_note():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateRevision, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="tl-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="tl-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="r", revision_id="r:rev1",
                                candidate_json={"name": "张三"}, evidence={})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        await db.commit()
        ws_id, cand_id = ws.id, cand.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "tl@b.com", "password": "secret123", "nickname": "T"})
        token = (await c.post("/api/v1/auth/login", json={"email": "tl@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r_note = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/notes",
                              json={"content": "初面通过"}, headers=h)
        assert r_note.status_code == 200
        r_tl = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/timeline", headers=h)
        assert r_tl.status_code == 200
        assert any(e["title"] == "备注：初面通过" for e in r_tl.json()["items"])
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_candidates_api.py::test_candidate_timeline_and_note -v`
预期：FAIL 404

- [x] **步骤 3：实现时间线/备注端点**

`backend/app/api/candidates.py` 追加：

```python
@router.get("/workspaces/{ws_id}/candidates/{candidate_id}/timeline")
async def get_timeline(ws_id: int, candidate_id: int,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _visible_candidate(db, ws_id, candidate_id, user)
    from app.models import CandidateEvent
    rows = await db.execute(select(CandidateEvent).where(CandidateEvent.candidate_id == candidate_id)
                            .order_by(CandidateEvent.created_at.desc()).limit(200))
    return {"items": [{"event_type": e.event_type, "title": e.title, "detail": e.detail,
                       "actor_id": e.actor_id, "created_at": e.created_at.isoformat()} for e in rows.scalars().all()]}


class NoteRequest(BaseModel):
    content: str


@router.post("/workspaces/{ws_id}/candidates/{candidate_id}/notes")
async def add_note(ws_id: int, candidate_id: int, body: NoteRequest,
                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _visible_candidate(db, ws_id, candidate_id, user)
    if not body.content or len(body.content) > 2000:
        raise HTTPException(400, "备注内容 1-2000 字符")
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.note,
                       title=f"备注：{body.content}", detail={"content": body.content}, actor_id=user.id)
    await db.commit()
    return {"candidate_id": candidate_id}
```

- [x] **步骤 4：运行测试验证通过**

运行：`pytest backend/tests/test_candidates_api.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/api/candidates.py backend/tests/test_candidates_api.py
git commit -m "feat: add candidate timeline and notes (P4 F8)"
```

---

### 任务 8：前端候选人列表/详情页

**文件：**
- 创建：`frontend/src/api/candidates.ts`
- 创建：`frontend/src/pages/CandidatesPage.tsx`
- 创建：`frontend/src/pages/CandidateDetailPage.tsx`
- 修改：`frontend/src/App.tsx`

- [x] **步骤 1：编写 API 客户端**

```ts
// frontend/src/api/candidates.ts
import { client } from './client';

export async function listCandidates(wsId: number, params: Record<string, unknown> = {}) {
  return client.get(`/workspaces/${wsId}/candidates`, { params }).then((r) => r.data);
}
export async function getCandidate(wsId: number, id: number) {
  return client.get(`/workspaces/${wsId}/candidates/${id}`).then((r) => r.data);
}
export async function overrideField(wsId: number, id: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/candidates/${id}/fields`, body).then((r) => r.data);
}
export async function softDelete(wsId: number, id: number) {
  return client.delete(`/workspaces/${wsId}/candidates/${id}`).then((r) => r.data);
}
export async function restoreCandidate(wsId: number, id: number) {
  return client.post(`/workspaces/${wsId}/candidates/${id}/restore`).then((r) => r.data);
}
export async function getTimeline(wsId: number, id: number) {
  return client.get(`/workspaces/${wsId}/candidates/${id}/timeline`).then((r) => r.data);
}
export async function addNote(wsId: number, id: number, content: string) {
  return client.post(`/workspaces/${wsId}/candidates/${id}/notes`, { content }).then((r) => r.data);
}
```

- [x] **步骤 2：编写列表页**

`frontend/src/pages/CandidatesPage.tsx`：工作区选择 + 筛选条件（状态/技能/城市/学历/年限/画像维度）+ 候选人卡片列表（姓名/状态/城市/学历/年限），点击跳详情。样式对齐 SearchPage。

- [x] **步骤 3：编写详情页**

`frontend/src/pages/CandidateDetailPage.tsx`：结构化字段展示（合并视图）+ 画像卡片 + 字段修正（选字段→override/clear） + 软删除/恢复按钮 + 时间线 + 备注输入。

- [x] **步骤 4：注册路由**

`frontend/src/App.tsx`：`/candidates` 与 `/candidates/:id` 路由（RequireAuth）。

- [x] **步骤 5：构建与测试**

```bash
cd frontend && npm run build && npx vitest run
```
预期：通过

- [x] **步骤 6：Commit**

```bash
git add frontend/src/api/candidates.ts frontend/src/pages/CandidatesPage.tsx frontend/src/pages/CandidateDetailPage.tsx frontend/src/App.tsx
git commit -m "feat: add candidate list and detail pages (P4 F8)"
```

---

### 任务 9：回归验证与台账

- [x] **步骤 1：全量回归**

```bash
cd backend && ../../.worktrees/p2-resume-parsing/.venv/bin/alembic upgrade head && cd .. && \
DATABASE_URL=... ../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests -q
```
预期：**全量 ≥ 197 + P4 新增全部通过**

- [x] **步骤 2：静态检查**

```bash
../.worktrees/p2-resume-parsing/.venv/bin/ruff check backend/app backend/tests && git diff --check
```

- [x] **步骤 3：更新台账**

在 `docs/superpowers/deviation-log.md` 追加 §12「P4 候选人管理（F8）实现与偏离」，记录 C-1~C-8 裁决与验证。

- [x] **步骤 4：勾选计划并提交**

```bash
git add -A && git commit -m "docs: 记录 P4 候选人管理实现偏差与验证（P4 F8）"
```

---

## 自检

**1. 规格覆盖度：**

| 需求 | 对应任务 |
|------|---------|
| 列表 + 多维筛选（状态/技能/城市/学历/年限/画像/渠道） | 任务 3、4 |
| 详情（结构化 + 画像 + 原文 IR 对照） | 任务 2、4 |
| 合并视图（latest revision + override/clear） | 任务 2 |
| 字段修正 override/clear + 乐观锁 | 任务 2、5 |
| 生命周期 active→deleted(30d)→purged + 恢复 | 任务 6 |
| 时间线（状态流转/修正/备注留痕） | 任务 1、5、6、7 |
| F9 池可见性（member 不可见 hired，跨租户 404） | 任务 4、6 |
| 审计（删除/修正/硬删 tombstone） | 任务 5、6 |
| 前端列表/详情/修正/生命周期/时间线 | 任务 8 |

**2. 占位符扫描：** 无 TODO/占位；`_path_get`/`_rev_id_of`/`_visible_candidate`/`_sha256` 为任务 5/6 明确的辅助函数，实现时在对应文件补齐。

**3. 类型一致性：** `build_effective_view`（任务 2）返回 `{candidate_id,name,status,deleted_until,fields,profile,latest_revision_id}`，在任务 4/5 消费一致；`append_event`（任务 5）签名在任务 5/6/7 复用一致；`list_candidates`（任务 3）返回 `(total, items)` 在任务 4 消费一致。

**已知边界（后续处理）：** 多人对比 + AI 对比分析（AI 决策辅助）；查重合并动作（F12）；override 数组元素关键字段配对与增删元素；重新解析（F8 re-parse）与并发；面试安排/反馈时间线（F13/F14）；purged 后台定时清理（30 天到期策略）。

---

## 执行交接

**计划已完成并保存到 `docs/superpowers/plans/2026-08-08-p4-candidate-management.md`。两种执行方式：**

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

**选哪种方式？**