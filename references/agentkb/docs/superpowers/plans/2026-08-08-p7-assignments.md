# P7 招聘管道与待面试表（F13）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现 F13 招聘管道与待面试表——候选人×职位指派记录（独立走完整管道）、9 态状态机（服务端强制校验）、HC 原子占位（hc_reserved/hc_filled）、待面试看板（职位阶段视图）、批量加入幂等、淘汰原因、池归属流转（F15 三池规则提前落地：hired/有进行中/rejected），并联动 F8 候选人时间线与审计。

**架构：** 新增 `assignments` 表（candidate_id + job_id 唯一，一条指派独立走状态机）+ `jobs` 增加 `hc_reserved`/`hc_filled` 列。状态机在 `assignment_service` 校验转移矩阵（终态不可流转）；HC 在职位行锁（SELECT FOR UPDATE）内做算术调整保证并发不超招；每次流转在同一事务内 append CandidateEvent + `recompute_candidate_pool`（F15 三池：任一 hired→hired；有进行中→active；否则最近终态 rejected/offer_rejected→rejected，closed_after_hire/closed_by_job 保持前池）。

**技术栈：** FastAPI、SQLAlchemy 2.0（async）、pgvector、pydantic v2、pytest、React（前端）。

**参考：** `docs/PRD.md` §7.2 F13（状态机转移矩阵/机器状态枚举/HC/待面试表）、§7.2 F15（三池流转/可逆性/查重联动）、§7.2 F9 权限矩阵、P5 `job_service.py`（职位行锁模式）、P4 `candidate_view.py`/`candidate_merge.py`（事务/事件模式）。

---

## 设计决策与歧义裁决（实现前必读）

| # | 歧义 / 取舍 | 依据 | 本计划裁决 |
|---|------------|------|-----------|
| P-1 | 指派模型与唯一约束 | PRD F13「同一 candidate_id + job_id 只能存在一条未删除指派记录」；F15「rejected 候选人可重新指派到**其他**职位」 | `assignments`（candidate_id/job_id/status/reject_reason/close_reason/idempotency_key/created_by），`UNIQUE(candidate_id, job_id)`——重新指派仅限其他职位（同职位复用禁止） |
| P-2 | 状态机与终态 | PRD F13 机器状态枚举正式冻结 | 9 态：pending_screen/screen_passed/interviewing/offer/hired/offer_rejected/rejected/closed_after_hire/closed_by_job；终态集合 `{hired, offer_rejected, rejected, closed_after_hire, closed_by_job}` 不可再流转；转移矩阵在服务端强制校验 |
| P-3 | F14 依赖闸门延后 | F13 转移矩阵引用「安排面试」「feedback recommend」等 F14 概念 | F13 内 `screen_passed→interviewing`、`interviewing→offer` 直接放开（无面试安排/反馈表）；F14 补闸门（recommend 才可 offer、安排面试才可 interviewing）。`close_by_job` 在 F13 落地（admin） |
| P-4 | HC 占位与并发 | PRD F13「职位行锁或原子条件更新保证不超招」 | `jobs` 加 `hc_reserved`/`hc_filled`（`headcount` 即 hc_total）；→offer 前校验 `hc_filled + hc_reserved < hc_total`，offer→hired 原子转 reservation→filled，offer→offer_rejected/淘汰/closed_* 释放 reservation；涉及 HC 的流转在职位行锁内做算术 |
| P-5 | 池流转（F15 提前落地） | PRD F13「指派记录结束后池归属按 F15 三池模型」；F15 语义澄清 | `recompute_candidate_pool`：任一 hired→hired；否则任一进行中（pending_screen/screen_passed/interviewing/offer）→active；否则最近终态为 rejected/offer_rejected→rejected，closed_* 保持前池。创建指派（rejected 回 active）、终态流转、入职聚合均同一事务内重算 |
| P-6 | 权限 | PRD F13 状态机 + F9 矩阵 | 指派/流转/入职 = member+；`closed_by_job`（职位关闭余下指派）= admin+；跨工作区 404；hired 候选人禁止重新指派 |
| P-7 | 幂等 | PRD F13「批量加入 UI 命令携带 idempotency_key，重复点击不得重复创建」 | `idempotency_key` 列 + 工作区唯一索引；重复 key 返回既有指派（不重复创建事件） |
| P-8 | 时间线/审计 | PRD F13「状态流转与时间线联动」；§8.2 审计 | 每次流转 append `CandidateEvent(status_changed/summary)` 到候选人时间线 + `add_event`（assignment.created/transitioned/hired，含 from/to/reason）；HC/池变化不单独建事件（随流转事件 detail 记录） |

---

## 文件结构

```
backend/
  alembic/versions/<new>_add_assignments.py    (新：assignments 表 + assignment_status enum + jobs.hc_reserved/hc_filled + 幂等索引)
  app/models/
    assignment.py                              (新：Assignment + AssignmentStatus)
    job.py                                     (修改：Job 增加 hc_reserved/hc_filled)
    __init__.py                                (修改：导出)
  app/services/
    assignment_service.py                      (新：create_assignment/batch_create/list_board/transition/hire/close_by_job/recompute_candidate_pool/_adjust_hc)
  app/api/
    assignments.py                             (新：创建/批量/看板/指派列表/流转/入职/职位关闭关闭指派)
    main.py                                    (修改：注册 assignments router)
  tests/
    test_assignment.py                         (新：状态机/池/HC 服务级)
    test_assignments_api.py                    (新：API 级)
  frontend/src/
    api/assignments.ts                         (新)
    pages/JobDetailPage.tsx                    (修改：待面试看板 + 指派/流转操作)
    pages/CandidatesPage.tsx                   (修改：批量加入待面试入口)
```

**领域边界**：P7 不改 P2 解析/P3 搜人/P4 候选人/P5 职位核心；新增指派域并复用职位/候选人模型。F14（面试安排/反馈/多轮）与 F15（入职聚合已在 P-5 落地、查重联动提示池归属）留后续。
---

### 任务 1：指派模型 + 迁移

**文件：**
- 创建：`backend/app/models/assignment.py`
- 修改：`backend/app/models/job.py`（Job 加 hc_reserved/hc_filled）
- 修改：`backend/app/models/__init__.py`
- 创建：`backend/alembic/versions/<new>_add_assignments.py`（autogenerate）
- 测试：`backend/tests/test_assignment.py`

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_assignment.py
import pytest


@pytest.mark.asyncio
async def test_assignment_model_roundtrip():
    from app.core.database import SessionLocal
    from app.models import (
        Assignment, AssignmentStatus, Candidate, CandidateStatus, Job, User, Workspace,
    )

    async with SessionLocal() as db:
        owner = User(email="asn-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="asn-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        job = Job(workspace_id=ws.id, name="后端开发", description="", headcount=2,
                  hc_reserved=0, hc_filled=0)
        db.add_all([cand, job])
        await db.flush()
        a = Assignment(workspace_id=ws.id, candidate_id=cand.id, job_id=job.id,
                       status=AssignmentStatus.pending_screen, idempotency_key="ik-1",
                       created_by=owner.id)
        db.add(a)
        await db.commit()
        got = await db.get(Assignment, a.id)
        assert got.status is AssignmentStatus.pending_screen
        assert got.idempotency_key == "ik-1"
        # 唯一约束 (candidate_id, job_id)
        from sqlalchemy.exc import IntegrityError
        db.add(Assignment(workspace_id=ws.id, candidate_id=cand.id, job_id=job.id,
                          status=AssignmentStatus.rejected, idempotency_key="ik-2",
                          created_by=owner.id))
        with pytest.raises(IntegrityError):
            await db.commit()
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_assignment.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：创建模型**

```python
# backend/app/models/assignment.py
import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK, TimestampMixin


class AssignmentStatus(str, enum.Enum):
    pending_screen = "pending_screen"
    screen_passed = "screen_passed"
    interviewing = "interviewing"
    offer = "offer"
    hired = "hired"
    offer_rejected = "offer_rejected"
    rejected = "rejected"
    closed_after_hire = "closed_after_hire"
    closed_by_job = "closed_by_job"


class Assignment(Base, TimestampMixin):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[AssignmentStatus] = mapped_column(Enum(AssignmentStatus, name="assignment_status", values_callable=lambda e: [m.value for m in e]), nullable=False, default=AssignmentStatus.pending_screen, index=True)
    reject_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        Index("uq_assignments_pair", "candidate_id", "job_id", unique=True),
        Index("uq_assignments_idem", "workspace_id", "idempotency_key", unique=True),
    )
```

> 说明：`(candidate_id, job_id)` 唯一（P-1 重新指派仅其他职位）；`(workspace_id, idempotency_key)` 部分唯一（幂等，P-7）；PG enum `assignment_status`。

`backend/app/models/job.py` 的 `Job` 增加：

```python
    hc_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hc_filled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

- [x] **步骤 4：生成迁移**

```bash
cd backend
../../.worktrees/p2-resume-parsing/.venv/bin/alembic revision --autogenerate -m "add assignments"
../../.worktrees/p2-resume-parsing/.venv/bin/alembic upgrade head
```

预期：迁移生成并应用；`assignments` + `assignment_status` enum + `jobs.hc_reserved/hc_filled` 创建。若 autogenerate 误判既有漂移（如候选事件索引），手动剔除无关项（同 P5 J-D1）。

- [x] **步骤 5：更新 __init__ 导出**

`backend/app/models/__init__.py` 追加导入与 `__all__`：`Assignment`、`AssignmentStatus`。

- [x] **步骤 6：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_assignment.py -v`
预期：PASS

- [x] **步骤 7：Commit**

```bash
git add backend/app/models/assignment.py backend/app/models/job.py backend/app/models/__init__.py backend/alembic/versions backend/tests/test_assignment.py
git commit -m "feat: add assignment model and job HC columns (P7 F13)"
```

---

### 任务 2：状态机 + 池 + HC 服务

**文件：**
- 创建：`backend/app/services/assignment_service.py`
- 测试：`backend/tests/test_assignment.py`（追加）

**验收（P-2/P-4/P-5）：** 转移矩阵服务端强制；终态不可流转；淘汰必填原因；→offer 校验 HC；offer→hired 转 reservation；offer 拒绝/淘汰释放；池按三池规则重算；创建指派（rejected 回 active）；入职聚合关闭余下指派。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_assignment.py 追加
import pytest


@pytest.mark.asyncio
async def test_transition_matrix_and_terminal():
    from app.core.database import SessionLocal
    from app.models import Assignment, AssignmentStatus, Candidate, CandidateStatus, Job, User, Workspace
    from app.services.assignment_service import AssignmentError, create_assignment, transition

    async with SessionLocal() as db:
        owner = User(email="asm-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="asm-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        job = Job(workspace_id=ws.id, name="后端", description="", headcount=3)
        db.add_all([cand, job])
        await db.commit()
        ws_id, cand_id, job_id = ws.id, cand.id, job.id

    async with SessionLocal() as db:
        a = await create_assignment(db, workspace_id=ws_id, candidate_id=cand_id, job_id=job_id,
                                    idempotency_key="t1", actor_id=owner.id)
        assert a.status is AssignmentStatus.pending_screen
        # 顺序流转
        a = await transition(db, assignment=a, to_state="screen_passed", actor_id=owner.id)
        assert a.status is AssignmentStatus.screen_passed
        a = await transition(db, assignment=a, to_state="interviewing", actor_id=owner.id)
        a = await transition(db, assignment=a, to_state="offer", actor_id=owner.id)
        assert a.status is AssignmentStatus.offer
        # 终态不可再流转
        a = await transition(db, assignment=a, to_state="hired", actor_id=owner.id)
        with pytest.raises(AssignmentError, match="终态"):
            await transition(db, assignment=a, to_state="rejected", actor_id=owner.id)
        # 非法跳转
        a2 = await create_assignment(db, workspace_id=ws_id, candidate_id=cand_id, job_id=job_id,
                                     idempotency_key="t2", actor_id=owner.id)
        with pytest.raises(AssignmentError, match="不允许"):
            await transition(db, assignment=a2, to_state="offer", actor_id=owner.id)


@pytest.mark.asyncio
async def test_reject_requires_reason_and_updates_pool():
    from app.core.database import SessionLocal
    from app.models import (
        Assignment, AssignmentStatus, Candidate, CandidateStatus, Job, User, Workspace,
    )
    from app.services.assignment_service import AssignmentError, create_assignment, transition

    async with SessionLocal() as db:
        owner = User(email="asm2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="asm2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        job = Job(workspace_id=ws.id, name="后端", description="", headcount=1)
        db.add_all([cand, job])
        await db.commit()
        ws_id, cand_id, job_id = ws.id, cand.id, job.id

    async with SessionLocal() as db:
        a = await create_assignment(db, workspace_id=ws_id, candidate_id=cand_id, job_id=job_id,
                                    idempotency_key="t3", actor_id=owner.id)
        with pytest.raises(AssignmentError, match="淘汰原因"):
            await transition(db, assignment=a, to_state="rejected", actor_id=owner.id)
        await transition(db, assignment=a, to_state="rejected", reject_reason="能力不匹配", actor_id=owner.id)
        # 无其他进行中指派 → 池 rejected
        cand = await db.get(Candidate, cand_id)
        assert cand.status is CandidateStatus.rejected


@pytest.mark.asyncio
async def test_hc_occupancy_and_hire_aggregation():
    from app.core.database import SessionLocal
    from app.models import (
        Assignment, AssignmentStatus, Candidate, CandidateStatus, Job, User, Workspace,
    )
    from app.services.assignment_service import (
        AssignmentError, create_assignment, hire, transition,
    )

    async with SessionLocal() as db:
        owner = User(email="asm3-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="asm3-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        job1 = Job(workspace_id=ws.id, name="后端", description="", headcount=1)
        job2 = Job(workspace_id=ws.id, name="前端", description="", headcount=1)
        db.add_all([cand, job1, job2])
        await db.commit()
        ws_id, cand_id = ws.id, cand.id

    async with SessionLocal() as db:
        a1 = await create_assignment(db, workspace_id=ws_id, candidate_id=cand_id, job_id=job1.id,
                                     idempotency_key="h1", actor_id=owner.id)
        a2 = await create_assignment(db, workspace_id=ws_id, candidate_id=cand_id, job_id=job2.id,
                                     idempotency_key="h2", actor_id=owner.id)
        a1 = await transition(db, assignment=a1, to_state="offer", actor_id=owner.id)
        a2 = await transition(db, assignment=a2, to_state="offer", actor_id=owner.id)
        job1 = await db.get(Job, job1.id)
        assert job1.hc_reserved == 1  # offer 占 reservation
        # HC 满 → 拒绝新 offer?  hc_total=1, reserved=1 → 满
        with pytest.raises(AssignmentError, match="HC"):
            await transition(db, assignment=a2, to_state="offer", actor_id=owner.id)
        # 入职 a1 → 聚合关闭 a2
        a1 = await hire(db, assignment=a1, actor_id=owner.id)
        job1 = await db.get(Job, job1.id)
        job2 = await db.get(Job, job2.id)
        assert job1.hc_filled == 1 and job1.hc_reserved == 0
        assert job2.hc_reserved == 0
        a2 = await db.get(Assignment, a2.id)
        assert a2.status is AssignmentStatus.closed_after_hire
        cand = await db.get(Candidate, cand_id)
        assert cand.status is CandidateStatus.hired
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_assignment.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现状态机服务**

```python
# backend/app/services/assignment_service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    Candidate,
    CandidateEvent,
    CandidateEventType,
    CandidateStatus,
    Job,
    JobStatus,
)
from app.services.candidate_lifecycle import append_event

TERMINAL = {AssignmentStatus.hired, AssignmentStatus.offer_rejected, AssignmentStatus.rejected,
            AssignmentStatus.closed_after_hire, AssignmentStatus.closed_by_job}
IN_PROGRESS = {AssignmentStatus.pending_screen, AssignmentStatus.screen_passed,
               AssignmentStatus.interviewing, AssignmentStatus.offer}

_TRANSITIONS = {
    AssignmentStatus.pending_screen: {AssignmentStatus.screen_passed, AssignmentStatus.rejected},
    AssignmentStatus.screen_passed: {AssignmentStatus.interviewing, AssignmentStatus.rejected},
    AssignmentStatus.interviewing: {AssignmentStatus.offer, AssignmentStatus.rejected},
    AssignmentStatus.offer: {AssignmentStatus.hired, AssignmentStatus.offer_rejected, AssignmentStatus.rejected},
}


class AssignmentError(Exception):
    pass


async def _reload_job(db, job_id: int) -> Job:
    row = await db.execute(select(Job).where(Job.id == job_id).with_for_update())
    return row.scalar_one()


async def recompute_candidate_pool(db: AsyncSession, candidate_id: int) -> None:
    """F15 三池规则（P-5）：任一 hired→hired；有进行中→active；否则最近终态 rejected/offer_rejected→rejected，closed_* 保持。"""
    cand = await db.get(Candidate, candidate_id)
    rows = (await db.execute(select(Assignment).where(
        Assignment.candidate_id == candidate_id))).scalars().all()
    if any(a.status is AssignmentStatus.hired for a in rows):
        cand.status = CandidateStatus.hired
    elif any(a.status in IN_PROGRESS for a in rows):
        cand.status = CandidateStatus.active
    else:
        latest = None
        for a in rows:
            if a.status in TERMINAL:
                if latest is None or a.updated_at > latest.updated_at:
                    latest = a
        if latest is not None and latest.status in (AssignmentStatus.rejected, AssignmentStatus.offer_rejected):
            cand.status = CandidateStatus.rejected
        else:
            cand.status = CandidateStatus.active  # closed_* 保持前池（默认 active）


async def create_assignment(db: AsyncSession, *, workspace_id: int, candidate_id: int, job_id: int,
                            idempotency_key: str | None, actor_id: int) -> Assignment:
    """加入待面试（P-1/P-4/P-7）：职位在招、HC 未满、幂等去重、rejected 回 active。"""
    if idempotency_key:
        existing = (await db.execute(select(Assignment).where(
            Assignment.workspace_id == workspace_id, Assignment.idempotency_key == idempotency_key))).scalar_one_or_none()
        if existing is not None:
            return existing
    job = await _reload_job(db, job_id)
    if job.status is not JobStatus.open:
        raise AssignmentError("职位已关闭，不可新增指派")
    if job.hc_filled >= job.headcount:
        raise AssignmentError("HC 已满，无法加入待面试")
    cand = await db.get(Candidate, candidate_id)
    if cand is None or cand.workspace_id != workspace_id:
        raise AssignmentError("候选人不存在")
    if cand.status is CandidateStatus.hired:
        raise AssignmentError("入职员工禁止重新指派")
    a = Assignment(workspace_id=workspace_id, candidate_id=candidate_id, job_id=job_id,
                   status=AssignmentStatus.pending_screen, idempotency_key=idempotency_key,
                   created_by=actor_id)
    db.add(a)
    await db.flush()
    await recompute_candidate_pool(db, candidate_id)  # rejected 候选人重新指派 → active
    await append_event(db, candidate_id=candidate_id, event_type=CandidateEventType.status_changed,
                       title=f"加入待面试「{job.name}」", detail={"job_id": job_id, "to": "pending_screen"},
                       actor_id=actor_id)
    return a


async def _adjust_hc(job: Job, prev: AssignmentStatus, next_: AssignmentStatus) -> None:
    """HC 算术（P-4）：offer 占 reservation，hired 转 filled，终态释放。"""
    if prev is AssignmentStatus.offer and next_ is not AssignmentStatus.offer:
        job.hc_reserved = max(0, job.hc_reserved - 1)
    if next_ is AssignmentStatus.offer and prev is not AssignmentStatus.offer:
        job.hc_reserved += 1
    if next_ is AssignmentStatus.hired:
        job.hc_filled += 1


async def transition(db: AsyncSession, *, assignment: Assignment, to_state: str,
                     reject_reason: str | None = None, close_reason: str | None = None,
                     actor_id: int) -> Assignment:
    """状态流转（P-2/P-3/P-6）：终态不可流转；淘汰必填原因；closed_by_job 仅 admin（API 层校验）。"""
    target = AssignmentStatus(to_state)
    if assignment.status in TERMINAL:
        raise AssignmentError("终态指派不可再流转")
    if target not in _TRANSITIONS[assignment.status]:
        raise AssignmentError(f"不允许从 {assignment.status.value} 流转到 {target.value}")
    if target is AssignmentStatus.rejected and not reject_reason:
        raise AssignmentError("淘汰原因必填")
    prev = assignment.status
    job = await _reload_job(db, assignment.job_id)
    if target is AssignmentStatus.offer:
        if job.hc_filled + job.hc_reserved >= job.headcount:
            raise AssignmentError("HC 已满，无法发 offer")
        if job.status is not JobStatus.open:
            raise AssignmentError("职位已关闭，不可进入 offer")
    if target is AssignmentStatus.screen_passed and job.status is not JobStatus.open:
        raise AssignmentError("职位已关闭，不可进入初筛")
    assignment.status = target
    if target is AssignmentStatus.rejected:
        assignment.reject_reason = reject_reason
    if target is AssignmentStatus.closed_by_job:
        if not close_reason:
            raise AssignmentError("关闭原因必填")
        assignment.close_reason = close_reason
    await _adjust_hc(job, prev, target)
    await recompute_candidate_pool(db, assignment.candidate_id)
    await append_event(db, candidate_id=assignment.candidate_id, event_type=CandidateEventType.status_changed,
                       title=f"指派流转 {prev.value}→{target.value}",
                       detail={"assignment_id": assignment.id, "job_id": assignment.job_id,
                               "from": prev.value, "to": target.value,
                               "reason": reject_reason or close_reason},
                       actor_id=actor_id)
    return assignment


async def hire(db: AsyncSession, *, assignment: Assignment, actor_id: int) -> Assignment:
    """入职聚合（P-5）：offer→hired，原子关闭该候选人其余进行中指派 → closed_after_hire，池 → hired。"""
    if assignment.status is not AssignmentStatus.offer:
        raise AssignmentError("仅 offer 状态可入职")
    job = await _reload_job(db, assignment.job_id)
    assignment.status = AssignmentStatus.hired
    await _adjust_hc(job, AssignmentStatus.offer, AssignmentStatus.hired)
    # 关闭其余进行中指派
    others = (await db.execute(select(Assignment).where(
        Assignment.candidate_id == assignment.candidate_id,
        Assignment.id != assignment.id,
        Assignment.status.in_(IN_PROGRESS)))).scalars().all()
    for other in others:
        other.status = AssignmentStatus.closed_after_hire
        other.close_reason = f"候选人入职职位 {job.name}"
        try:
            ojob = await _reload_job(db, other.job_id)
            await _adjust_hc(ojob, other.status, AssignmentStatus.closed_after_hire)
        except AssignmentError:
            pass
    await recompute_candidate_pool(db, assignment.candidate_id)
    await append_event(db, candidate_id=assignment.candidate_id, event_type=CandidateEventType.status_changed,
                       title=f"入职「{job.name}」", detail={"assignment_id": assignment.id, "job_id": job.id},
                       actor_id=actor_id)
    return assignment
```

> 说明：`create_assignment` 幂等返回既有；`transition` 校验矩阵 + 原因 + HC + 池；`hire` 入职聚合关闭余下指派（closed_after_hire 保持前池，池由 recompute 置 hired）。`_reload_job` 用职位行锁（P-4）。

- [x] **步骤 4：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_assignment.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/assignment_service.py backend/tests/test_assignment.py
git commit -m "feat: add assignment state machine pool and HC service (P7 F13)"
```

---

### 任务 3：指派 API（创建/批量/看板/列表）

**文件：**
- 创建：`backend/app/api/assignments.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_assignments_api.py`

**验收（P-1/P-6/P-7）：** `POST /jobs/{job_id}/assignments`（单条，member+）、`POST /jobs/{job_id}/assignments/batch`（批量，幂等）、`GET /jobs/{job_id}/board`（阶段视图）、`GET /candidates/{id}/assignments`（历史）；跨工作区 404；hired 拒绝。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_assignments_api.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _seed(ws_id: int):
    from app.core.database import SessionLocal
    from app.models import Assignment, AssignmentStatus, Candidate, CandidateStatus

    async with SessionLocal() as db:
        cand = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        db.add(cand)
        await db.flush()
        a = Assignment(workspace_id=ws_id, candidate_id=cand.id, job_id=1, status=AssignmentStatus.pending_screen)
        db.add(a)
        await db.commit()
        return cand.id


@pytest.mark.asyncio
async def test_assign_batch_and_board(monkeypatch):
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, Job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "as-api@b.com", "password": "secret123", "nickname": "A"})
        token = (await c.post("/api/v1/auth/login", json={"email": "as-api@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "AS-API-WS"}, headers=h)).json()["id"]
        job = Job(workspace_id=ws_id, name="后端", description="", headcount=5)
        db = None
        async with SessionLocal() as db:
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=5)
            db.add(job)
            await db.flush()
            job_id = job.id
            cands = [Candidate(workspace_id=ws_id, status=CandidateStatus.active, name=f"C{i}",
                               structured_data={}, search_text="") for i in range(2)]
            db.add_all(cands)
            await db.flush()
            cand_ids = [c.id for c in cands]
            await db.commit()

        # 单条指派
        r = await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/assignments", headers=h,
                         json={"candidate_id": cand_ids[0], "idempotency_key": "api-1"})
        assert r.status_code == 200
        assert r.json()["status"] == "pending_screen"
        # 幂等：重复 key 返回既有
        r2 = await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/assignments", headers=h,
                          json={"candidate_id": cand_ids[0], "idempotency_key": "api-1"})
        assert r2.status_code == 200 and r2.json()["assignment_id"] == r.json()["assignment_id"]
        # 批量
        r3 = await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/assignments/batch", headers=h,
                          json={"candidate_ids": cand_ids, "idempotency_key": "api-b1"})
        assert r3.status_code == 200
        assert len(r3.json()["items"]) >= 2
        # 看板
        r4 = await c.get(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/board", headers=h)
        assert r4.status_code == 200
        assert r4.json()["groups"]["pending_screen"] >= 2
        # 候选指派历史
        r5 = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_ids[0]}/assignments", headers=h)
        assert r5.status_code == 200 and r5.json()["items"]
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_assignments_api.py -v`
预期：FAIL，报错 404（路由不存在）

- [x] **步骤 3：实现指派 API**

```python
# backend/app/api/assignments.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Assignment, Candidate, Job, User, WorkspaceMember
from app.services.assignment_service import (
    AssignmentError,
    create_assignment,
    transition,
)

router = APIRouter(prefix="/api/v1", tags=["assignments"])


async def _member_info(db: AsyncSession, ws_id: int, user_id: int) -> WorkspaceMember:
    row = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "资源不存在")
    return row


def _role_of(membership: WorkspaceMember) -> str:
    return membership.role.value if hasattr(membership.role, "value") else str(membership.role)


async def _visible_job(db: AsyncSession, ws_id: int, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None or job.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    return job


async def _visible_assignment(db: AsyncSession, ws_id: int, assignment_id: int) -> Assignment:
    a = await db.get(Assignment, assignment_id)
    if a is None or a.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    return a


class AssignRequest(BaseModel):
    candidate_id: int
    idempotency_key: str | None = Field(None, max_length=64)


class BatchAssignRequest(BaseModel):
    candidate_ids: list[int]
    idempotency_key: str | None = Field(None, max_length=64)


@router.post("/workspaces/{ws_id}/jobs/{job_id}/assignments")
async def assign_one(ws_id: int, job_id: int, body: AssignRequest,
                     user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    await _visible_job(db, ws_id, job_id)
    try:
        a = await create_assignment(db, workspace_id=ws_id, candidate_id=body.candidate_id,
                                    job_id=job_id, idempotency_key=body.idempotency_key, actor_id=user.id)
    except AssignmentError as exc:
        raise HTTPException(400, str(exc))
    from app.services.audit import add_event
    await add_event(db, action="assignment.created", result="success", resource_type="assignment",
                    resource_id=str(a.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"candidate_id": a.candidate_id, "job_id": job_id})
    await db.commit()
    return {"assignment_id": a.id, "candidate_id": a.candidate_id, "job_id": a.job_id, "status": a.status.value}


@router.post("/workspaces/{ws_id}/jobs/{job_id}/assignments/batch")
async def assign_batch(ws_id: int, job_id: int, body: BatchAssignRequest,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    await _visible_job(db, ws_id, job_id)
    items = []
    for cid in body.candidate_ids:
        try:
            a = await create_assignment(db, workspace_id=ws_id, candidate_id=cid, job_id=job_id,
                                        idempotency_key=body.idempotency_key, actor_id=user.id)
            items.append({"candidate_id": cid, "assignment_id": a.id, "status": a.status.value})
        except AssignmentError as exc:
            items.append({"candidate_id": cid, "error": str(exc)})
    from app.services.audit import add_event
    await add_event(db, action="assignment.batch_created", result="success", resource_type="assignment",
                    workspace_id=ws_id, actor_id=user.id,
                    payload={"job_id": job_id, "count": len([i for i in items if "error" not in i])})
    await db.commit()
    return {"job_id": job_id, "items": items}


@router.get("/workspaces/{ws_id}/jobs/{job_id}/board")
async def job_board(ws_id: int, job_id: int,
                    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    job = await _visible_job(db, ws_id, job_id)
    from app.models import Candidate
    rows = (await db.execute(select(Assignment, Candidate).join(
        Candidate, Candidate.id == Assignment.candidate_id).where(
        Assignment.workspace_id == ws_id, Assignment.job_id == job_id))).all()
    groups: dict[str, list] = {}
    for a, cand in rows:
        groups.setdefault(a.status.value, []).append({
            "assignment_id": a.id, "candidate_id": cand.id, "name": cand.name,
            "status": a.status.value, "reject_reason": a.reject_reason,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        })
    return {"job_id": job_id, "job_name": job.name, "groups": groups}


@router.get("/workspaces/{ws_id}/candidates/{candidate_id}/assignments")
async def candidate_assignments(ws_id: int, candidate_id: int,
                                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    rows = (await db.execute(select(Assignment, Job).join(
        Job, Job.id == Assignment.job_id).where(
        Assignment.workspace_id == ws_id, Assignment.candidate_id == candidate_id)
        .order_by(Assignment.id.desc()))).all()
    return {"items": [{"assignment_id": a.id, "job_id": j.id, "job_name": j.name,
                       "status": a.status.value, "reject_reason": a.reject_reason,
                       "updated_at": a.updated_at.isoformat() if a.updated_at else None}
                      for a, j in rows]}
```

`backend/app/main.py`：`from app.api import assignments` + `app.include_router(assignments.router)`。

- [x] **步骤 4：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_assignments_api.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/api/assignments.py backend/app/main.py backend/tests/test_assignments_api.py
git commit -m "feat: add assignment create batch and board endpoints (P7 F13)"
```

---

### 任务 4：流转/入职/职位关闭 API

**文件：**
- 修改：`backend/app/api/assignments.py`
- 测试：`backend/tests/test_assignments_api.py`（追加）

**验收（P-2/P-3/P-6）：** `POST /assignments/{id}/transition`（member+，淘汰必填原因，closed_by_job 仅 admin）、`POST /assignments/{id}/hire`（入职聚合）。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_assignments_api.py 追加
@pytest.mark.asyncio
async def test_transition_and_hire_api(monkeypatch):
    from app.core.database import SessionLocal
    from app.models import Assignment, AssignmentStatus, Candidate, CandidateStatus, Job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "as-t@b.com", "password": "secret123", "nickname": "T"})
        token = (await c.post("/api/v1/auth/login", json={"email": "as-t@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "AS-T-WS"}, headers=h)).json()["id"]
        async with SessionLocal() as db:
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=3)
            db.add(job)
            await db.flush()
            job_id = job.id
            cand = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                             structured_data={}, search_text="")
            db.add(cand)
            await db.flush()
            cand_id = cand.id
            await db.commit()
        a_id = (await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/assignments", headers=h,
                             json={"candidate_id": cand_id, "idempotency_key": "tr-1"})).json()["assignment_id"]
        # 淘汰缺原因 400
        r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=h,
                         json={"to_state": "rejected"})
        assert r.status_code == 400
        # 正常流转到 offer
        for s in ("screen_passed", "interviewing", "offer"):
            r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=h,
                             json={"to_state": s})
            assert r.status_code == 200, r.text
        # 入职
        r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/hire", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "hired"
        async with SessionLocal() as db:
            cand = await db.get(Candidate, cand_id)
            assert cand.status is CandidateStatus.hired
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_assignments_api.py::test_transition_and_hire_api -v`
预期：FAIL 404（端点未实现）

- [x] **步骤 3：实现流转/入职端点**

`backend/app/api/assignments.py` 追加：

```python
class TransitionRequest(BaseModel):
    to_state: str
    reject_reason: str | None = Field(None, max_length=256)
    close_reason: str | None = Field(None, max_length=256)


@router.post("/workspaces/{ws_id}/assignments/{assignment_id}/transition")
async def transition_assignment(ws_id: int, assignment_id: int, body: TransitionRequest,
                                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    role = _role_of(membership)
    a = await _visible_assignment(db, ws_id, assignment_id)
    if body.to_state == "closed_by_job" and role not in ("admin", "owner"):
        raise HTTPException(403, "仅管理员可关闭余下指派")
    try:
        a = await transition(db, assignment=a, to_state=body.to_state,
                             reject_reason=body.reject_reason, close_reason=body.close_reason,
                             actor_id=user.id)
    except AssignmentError as exc:
        raise HTTPException(400, str(exc))
    from app.services.audit import add_event
    await add_event(db, action="assignment.transitioned", result="success", resource_type="assignment",
                    resource_id=str(a.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"to_state": a.status.value})
    await db.commit()
    return {"assignment_id": a.id, "status": a.status.value}


@router.post("/workspaces/{ws_id}/assignments/{assignment_id}/hire")
async def hire_assignment(ws_id: int, assignment_id: int,
                          user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    a = await _visible_assignment(db, ws_id, assignment_id)
    from app.services.assignment_service import hire
    try:
        a = await hire(db, assignment=a, actor_id=user.id)
    except AssignmentError as exc:
        raise HTTPException(400, str(exc))
    from app.services.audit import add_event
    await add_event(db, action="assignment.hired", result="success", resource_type="assignment",
                    resource_id=str(a.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"candidate_id": a.candidate_id})
    await db.commit()
    return {"assignment_id": a.id, "status": a.status.value}
```

- [x] **步骤 4：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_assignments_api.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/api/assignments.py backend/tests/test_assignments_api.py
git commit -m "feat: add assignment transition and hire endpoints (P7 F13)"
```

---

### 任务 5：前端待面试看板 + 指派/流转

**文件：**
- 创建：`frontend/src/api/assignments.ts`
- 修改：`frontend/src/pages/JobDetailPage.tsx`
- 修改：`frontend/src/pages/CandidatesPage.tsx`

- [x] **步骤 1：API 客户端**

```ts
// frontend/src/api/assignments.ts
import { client } from "./client";

export async function assignCandidate(wsId: number, jobId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/jobs/${jobId}/assignments`, body).then((r) => r.data);
}
export async function assignBatch(wsId: number, jobId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/jobs/${jobId}/assignments/batch`, body).then((r) => r.data);
}
export async function jobBoard(wsId: number, jobId: number) {
  return client.get(`/workspaces/${wsId}/jobs/${jobId}/board`).then((r) => r.data);
}
export async function transitionAssignment(wsId: number, id: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/assignments/${id}/transition`, body).then((r) => r.data);
}
export async function hireAssignment(wsId: number, id: number) {
  return client.post(`/workspaces/${wsId}/assignments/${id}/hire`).then((r) => r.data);
}
```

- [x] **步骤 2：职位详情页加待面试看板**

`frontend/src/pages/JobDetailPage.tsx`：新增「待面试看板」区块——按状态分组展示指派（`/board`），每条提供流转按钮（初筛通过/安排面试→面试中/发 offer/淘汰(填原因)/入职），以及「加入待面试」(输入候选人 ID)。样式对齐现有。

- [x] **步骤 3：候选人列表加入待面试入口**

`frontend/src/pages/CandidatesPage.tsx`：每行加「加入待面试」按钮（选择职位后调用 assignCandidate）。

- [x] **步骤 4：构建与测试**

```bash
cd frontend && npm install && npm run build && npx vitest run
```

预期：通过

- [x] **步骤 5：Commit**

```bash
git add frontend/src/api/assignments.ts frontend/src/pages/JobDetailPage.tsx frontend/src/pages/CandidatesPage.tsx
git commit -m "feat: add assignment board and transition UI (P7 F13)"
```

---

### 任务 6：回归验证与台账

- [x] **步骤 1：全量回归**

```bash
export MODEL_KEY_ENC_KEY="..." && export JWT_SECRET="..." && export DATABASE_URL="..."
../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests -q
```

预期：全量通过（main 241 + P7 新增全部）

- [x] **步骤 2：静态检查**

```bash
../.worktrees/p2-resume-parsing/.venv/bin/ruff check backend/app backend/tests && git diff --check
```

- [x] **步骤 3：更新台账**

在 `docs/superpowers/deviation-log.md` 追加 §15「P7 招聘管道与待面试表（F13）实现与偏离」，记录 P-1~P-8 裁决与验证。

- [x] **步骤 4：勾选计划并提交**

```bash
git add -A && git commit -m "docs: 记录 P7 招聘管道实现偏差与验证（P7 F13）"
```

---

## 自检

**1. 规格覆盖度：**

| 需求 | 对应任务 |
|------|---------|
| 指派记录（候选人×职位，独立走管道） | 任务 1、3 |
| 9 态状态机 + 转移矩阵服务端强制 | 任务 2 |
| 终态不可流转 / 淘汰原因必填 | 任务 2 |
| HC 原子占位（hc_reserved/hc_filled 转填） | 任务 1、2 |
| 待面试看板（职位阶段视图） | 任务 3、5 |
| 批量加入 + idempotency_key 幂等 | 任务 3 |
| 入职聚合关闭余下指派（closed_after_hire） | 任务 2、4 |
| 职位关闭后 admin 关闭指派（closed_by_job） | 任务 2、4 |
| 池三池规则流转（hired/active/rejected） | 任务 2 |
| 时间线/审计联动 | 任务 2、3、4 |
| 前端看板 + 指派/流转 | 任务 5 |

**2. 占位符扫描：** 无 TODO/占位；`create_assignment`/`transition`/`hire`/`recompute_candidate_pool` 在任务 2 定义、任务 3/4 API 消费一致；`_visible_job`/`_visible_assignment`/`_member_info` 在任务 3 定义、任务 4 复用。

**3. 类型一致性：** `AssignmentStatus` 枚举在任务 1 定义、任务 2/3/4 一致；`transition` 返回 Assignment 在服务/API 一致；`hire` 聚合关闭在任务 2 定义、任务 4 消费一致；`_adjust_hc` 只被服务内部调用。

**已知边界（后续处理）：** F14 面试安排/反馈闸门（interviewing→offer 需 recommend、screen_passed→interviewing 需安排面试）、多轮 interview_round、反馈 AI 总结、48h 超时提醒；F15 查重联动（rejected/hired 再上传提示池归属）；职位关闭后 interviews 完成/转派的完整流转（closed_by_job vs 完成）；批量指派单职位多候选人超过 HC 的整批语义（逐条报错）。
