# P8 面试安排与反馈闭环（F14）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现 F14 面试安排与反馈闭环——每轮独立 `interview_round`（候选人+职位+面试官+时间）、结构化反馈（评分 1-5 / 结论 advance/recommend/reject/hold / 评语）多轮逐轮记录、**收紧 F13 状态机闸门**（`screen_passed→interviewing` 需已安排面试、`interviewing→offer` 需当前轮 recommend 且必填完整）、反馈 AI 总结（优势/风险/建议，可编辑、保留原始评语）、48h 超时未反馈站内待办提醒。

**架构：** 新增 `interview_rounds` 表（assignment_id + round_no 递增；feedback 当前值 + `feedback_history` JSONB 保留修改历史；`ai_summary` JSONB 存 AI 总结，原始评语不动）。在 `assignment_service.transition` 中叠加 F14 闸门（目标为 interviewing/offer 时校验 round 存在与反馈结论）。面试安排/反馈/AI 总结服务独立 `interview_service`；AI 总结复用 `LLMClient.chat_json`（经 outbound gateway）。超时待办为只读查询（scheduled_at + 48h 无反馈）。

**技术栈：** FastAPI、SQLAlchemy 2.0（async）、pgvector、pydantic v2、pytest、React（前端）。

**参考：** `docs/PRD.md` §7.2 F14、§7.2 F13 状态机转移矩阵（第 357 行反馈枚举冻结）、§7.2 F9 权限矩阵、P7 `assignment_service.py`（状态机/行锁模式）、P5 `jobs.py` 的 `_get_llm` 模式。

---

## 设计决策与歧义裁决（实现前必读）

| # | 歧义 / 取舍 | 依据 | 本计划裁决 |
|---|------------|------|-----------|
| I-1 | interview_round 模型 | PRD F14「每一轮为独立 interview_round…同一轮只能有一份当前有效反馈，修改产生新 revision 并保留历史」 | `interview_rounds`（assignment_id/round_no 递增/interviewer_id/scheduled_at/score/conclusion/comment/feedback_at/feedback_history JSONB/ai_summary JSONB）；历史用 `feedback_history` JSONB 数组（append 旧值），当前值存列；`ai_summary` 存 `{advantages, risks, suggestions}`，`comment` 不入总结（保留原始评语） |
| I-2 | 状态机闸门收紧 | PRD F13 矩阵「screen_passed→安排面试→interviewing（安排完成）」「interviewing→发 offer（当前轮反馈 recommend 且必填完整）」；P7 P-3 裁决延后 | `transition` 目标为 interviewing：要求该 assignment 已存在任一 round（安排过）；目标为 offer：要求存在结论 recommend 且 score/comment 完整的 round。不满足抛 `AssignmentError`（400） |
| I-3 | 反馈结论语义 | PRD F14「recommend 只允许…触发 offer；advance 只允许创建下一轮；hold 不改变指派状态」 | 反馈只写 round，不直接改指派：recommend→提示可发 offer（仍走 transition）；advance→提示需显式安排下一轮；hold→无操作；reject→提示可淘汰。`interviewing→offer` 由 transition 闸门强制 |
| I-4 | AI 总结 | PRD F14「一键生成结构化总结（优势/风险/建议），可编辑、保留原始评语」 | `summarize` 单次 LLM 调用（free 评语→JSON `{advantages, risks, suggestions}`），存 `ai_summary`；`comment` 永不覆盖；可重复调用覆盖（保留原始评语在 history） |
| I-5 | 超时提醒 | PRD F14「每轮 48 小时未填写反馈→站内待办提醒；round_id + reminder_type 幂等」 | MVP 为只读查询 `GET /workspaces/{ws_id}/interviews/overdue`（当前用户为面试官的 round，scheduled_at+48h<now 且无反馈）；待办视图天然幂等，推送渠道留 V1.1 |
| I-6 | 权限 | PRD F14「面试官只是负责人字段，无权限差异」；F9 矩阵「面试安排/反馈/AI 总结 允许」 | 安排/反馈/总结 = member+；`interviewer_id` 须为工作区成员（WorkspaceMember 校验）；面试官不因负责人身份获得对候选人/指派更高的读权限 |
| I-7 | F15 查重联动 | PRD F15「rejected/hired 再上传提示池归属与历史」 | 已由 P2 pending_review + P6 merge + F13 `candidate_assignments` 历史覆盖路径；本轮记录为已接受边界，不单独开发 |

---

## 文件结构

```
backend/
  alembic/versions/<new>_add_interview_rounds.py   (新：interview_rounds 表)
  app/models/
    interview_round.py                             (新：InterviewRound + FeedbackConclusion)
    __init__.py                                    (修改：导出)
  app/services/
    interview_service.py                           (新：schedule_round/submit_feedback/ai_summarize/list_rounds/list_overdue)
    assignment_service.py                          (修改：transition 叠加 F14 闸门)
  app/api/
    interviews.py                                  (新：安排/反馈/总结/多轮列表/overdue 待办)
    main.py                                        (修改：注册 interviews router)
  tests/
    test_interview.py                              (新：round/反馈/AI/overdue/闸门)
    test_interviews_api.py                         (新：API 级)
  frontend/src/
    api/interviews.ts                              (新)
    pages/JobDetailPage.tsx                        (修改：interviewing 组安排面试/反馈/AI 总结按钮)
```

**领域边界**：P8 不改 F13 状态机核心（仅叠加两处 target 闸门）；不改 P2/P5 解析/职位；面试安排不接日历（P2 预留）。
---

### 任务 1：interview_rounds 模型 + 迁移

**文件：**
- 创建：`backend/app/models/interview_round.py`
- 修改：`backend/app/models/__init__.py`
- 创建：`backend/alembic/versions/<new>_add_interview_rounds.py`（autogenerate）
- 测试：`backend/tests/test_interview.py`

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_interview.py
import pytest


@pytest.mark.asyncio
async def test_interview_round_roundtrip():
    from app.core.database import SessionLocal
    from app.models import (
        Assignment, AssignmentStatus, Candidate, CandidateStatus, FeedbackConclusion,
        InterviewRound, Job, User, Workspace,
    )

    async with SessionLocal() as db:
        owner = User(email="irv-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="irv-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        job = Job(workspace_id=ws.id, name="后端", description="", headcount=1)
        db.add_all([cand, job])
        await db.flush()
        a = Assignment(workspace_id=ws.id, candidate_id=cand.id, job_id=job.id,
                       status=AssignmentStatus.interviewing)
        db.add(a)
        await db.flush()
        from datetime import UTC, datetime
        r = InterviewRound(workspace_id=ws.id, assignment_id=a.id, round_no=1,
                           interviewer_id=owner.id, scheduled_at=datetime.now(UTC),
                           score=4, conclusion=FeedbackConclusion.advance, comment="技术不错",
                           feedback_history=[{"score": 3, "conclusion": "hold", "comment": "初版"}],
                           ai_summary={"advantages": ["技术"], "risks": [], "suggestions": []})
        db.add(r)
        await db.commit()
        got = await db.get(InterviewRound, r.id)
        assert got.conclusion is FeedbackConclusion.advance
        assert got.feedback_history[0]["comment"] == "初版"
        assert got.ai_summary["advantages"] == ["技术"]
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_interview.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：创建模型**

```python
# backend/app/models/interview_round.py
import enum
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPK, TimestampMixin


class FeedbackConclusion(str, enum.Enum):
    advance = "advance"
    recommend = "recommend"
    reject = "reject"
    hold = "hold"


class InterviewRound(Base, TimestampMixin):
    __tablename__ = "interview_rounds"
    __table_args__ = (Index("ix_interview_rounds_assignment_no", "assignment_id", "round_no"),)
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    interviewer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conclusion: Mapped[FeedbackConclusion | None] = mapped_column(Enum(FeedbackConclusion, name="feedback_conclusion", values_callable=lambda e: [m.value for m in e]), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feedback_history = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False, default=list)
    ai_summary = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
```

- [x] **步骤 4：生成迁移**

```bash
cd backend
../../.worktrees/p2-resume-parsing/.venv/bin/alembic revision --autogenerate -m "add interview rounds"
../../.worktrees/p2-resume-parsing/.venv/bin/alembic upgrade head
```

预期：迁移生成并应用；`interview_rounds` + `feedback_conclusion` enum。若 autogenerate 误判既有漂移，手动剔除（同 P5 J-D1）。

- [x] **步骤 5：更新 __init__ 导出**

`backend/app/models/__init__.py` 追加：`FeedbackConclusion`、`InterviewRound`。

- [x] **步骤 6：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_interview.py -v`
预期：PASS

- [x] **步骤 7：Commit**

```bash
git add backend/app/models/interview_round.py backend/app/models/__init__.py backend/alembic/versions backend/tests/test_interview.py
git commit -m "feat: add interview round model and feedback history (P8 F14)"
```

---

### 任务 2：面试服务 + 状态机闸门

**文件：**
- 创建：`backend/app/services/interview_service.py`
- 修改：`backend/app/services/assignment_service.py`
- 测试：`backend/tests/test_interview.py`（追加）

**验收（I-1/I-2/I-3/I-4/I-5）：** 安排面试/提交反馈（history append）/AI 总结/list/overdue；`transition` interviewing/offer 目标闸门生效。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_interview.py 追加
import pytest


class FakeLLM:
    async def chat_json(self, system, user, schema):
        return {"advantages": ["技术扎实"], "risks": ["沟通一般"], "suggestions": ["补充团队协作题"]}


@pytest.mark.asyncio
async def test_schedule_feedback_summarize_and_overdue():
    from datetime import UTC, datetime, timedelta

    from app.core.database import SessionLocal
    from app.models import (
        Assignment, AssignmentStatus, Candidate, CandidateStatus, FeedbackConclusion,
        InterviewRound, Job, User, Workspace,
    )
    from app.services.interview_service import (
        InterviewError, ai_summarize, list_overdue, schedule_round, submit_feedback,
    )

    async with SessionLocal() as db:
        owner = User(email="irv2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="irv2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        job = Job(workspace_id=ws.id, name="后端", description="", headcount=1)
        db.add_all([cand, job])
        await db.flush()
        a = Assignment(workspace_id=ws.id, candidate_id=cand.id, job_id=job.id,
                       status=AssignmentStatus.interviewing)
        db.add(a)
        await db.flush()
        ws_id, a_id = ws.id, a.id
        await db.commit()

    async with SessionLocal() as db:
        r1 = await schedule_round(db, workspace_id=ws_id, assignment_id=a_id,
                                  interviewer_id=owner.id, scheduled_at=datetime.now(UTC), actor_id=owner.id)
        assert r1.round_no == 1
        r2 = await schedule_round(db, workspace_id=ws_id, assignment_id=a_id,
                                  interviewer_id=owner.id, scheduled_at=datetime.now(UTC), actor_id=owner.id)
        assert r2.round_no == 2  # round_no 递增
        # 反馈 + history
        r1 = await submit_feedback(db, round_id=r1.id, score=4, conclusion="advance",
                                   comment="技术不错", actor_id=owner.id)
        assert r1.feedback_history[0]["comment"] == "技术不错"
        r1 = await submit_feedback(db, round_id=r1.id, score=5, conclusion="recommend",
                                   comment="推荐", actor_id=owner.id)
        assert len(r1.feedback_history) == 2
        assert r1.conclusion is FeedbackConclusion.recommend
        # AI 总结（保留原始评语）
        r1 = await ai_summarize(db, round_id=r1.id, llm=FakeLLM(), actor_id=owner.id)
        assert r1.ai_summary["advantages"] == ["技术扎实"]
        assert r1.comment == "推荐"  # 原始评语保留
        # 超时：把 r2 的 scheduled_at 设为 2 天前且无反馈 → overdue
        r2.scheduled_at = datetime.now(UTC) - timedelta(days=2)
        await db.commit()
        overdue = await list_overdue(db, workspace_id=ws_id, interviewer_id=owner.id)
        assert any(o["round_id"] == r2.id for o in overdue)


@pytest.mark.asyncio
async def test_transition_gates_interviewing_and_offer():
    from datetime import UTC, datetime

    from app.core.database import SessionLocal
    from app.models import (
        Assignment, AssignmentStatus, Candidate, CandidateStatus, Job, User, Workspace,
    )
    from app.services.assignment_service import AssignmentError, create_assignment, transition
    from app.services.interview_service import schedule_round, submit_feedback

    async with SessionLocal() as db:
        owner = User(email="gate-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="gate-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        job = Job(workspace_id=ws.id, name="后端", description="", headcount=2)
        db.add_all([cand, job])
        await db.commit()
        ws_id, cand_id, job_id = ws.id, cand.id, job.id

    async with SessionLocal() as db:
        a = await create_assignment(db, workspace_id=ws_id, candidate_id=cand_id, job_id=job_id,
                                    idempotency_key="ig", actor_id=owner.id)
        a = await transition(db, assignment=a, to_state="screen_passed", actor_id=owner.id)
        # 未安排面试 → interviewing 被拒
        with pytest.raises(AssignmentError, match="面试"):
            await transition(db, assignment=a, to_state="interviewing", actor_id=owner.id)
        # 安排面试后可通过
        r = await schedule_round(db, workspace_id=ws_id, assignment_id=a.id,
                                 interviewer_id=owner.id, scheduled_at=datetime.now(UTC), actor_id=owner.id)
        a = await transition(db, assignment=a, to_state="interviewing", actor_id=owner.id)
        assert a.status is AssignmentStatus.interviewing
        # 无 recommend 反馈 → offer 被拒
        r = await submit_feedback(db, round_id=r.id, score=3, conclusion="hold", comment="待定", actor_id=owner.id)
        with pytest.raises(AssignmentError, match="recommend"):
            await transition(db, assignment=a, to_state="offer", actor_id=owner.id)
        # recommend 完整 → offer 通过
        r = await submit_feedback(db, round_id=r.id, score=5, conclusion="recommend", comment="推荐", actor_id=owner.id)
        a = await transition(db, assignment=a, to_state="offer", actor_id=owner.id)
        assert a.status is AssignmentStatus.offer
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_interview.py -v`
预期：FAIL（interview_service 缺失 / 闸门未生效）

- [x] **步骤 3：实现面试服务**

```python
# backend/app/services/interview_service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    FeedbackConclusion,
    InterviewRound,
    WorkspaceMember,
)
from app.services.candidate_lifecycle import append_event


class InterviewError(Exception):
    pass


async def _visible_round(db: AsyncSession, round_id: int) -> InterviewRound:
    r = await db.get(InterviewRound, round_id)
    if r is None:
        raise InterviewError("面试轮不存在")
    return r


async def schedule_round(db: AsyncSession, *, workspace_id: int, assignment_id: int,
                         interviewer_id: int, scheduled_at, actor_id: int) -> InterviewRound:
    """安排面试（I-1/I-6）：round_no 递增；assignment 须在 screen_passed/interviewing；面试官须为工作区成员。"""
    a = await db.get(Assignment, assignment_id)
    if a is None or a.workspace_id != workspace_id:
        raise InterviewError("指派不存在")
    if a.status not in (AssignmentStatus.screen_passed, AssignmentStatus.interviewing):
        raise InterviewError("仅初筛通过/面试中可安排面试")
    member = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == interviewer_id))).scalar_one_or_none()
    if member is None:
        raise InterviewError("面试官必须是工作区成员")
    latest = (await db.execute(select(InterviewRound).where(
        InterviewRound.assignment_id == assignment_id)
        .order_by(InterviewRound.round_no.desc()))).scalars().first()
    r = InterviewRound(workspace_id=workspace_id, assignment_id=assignment_id,
                       round_no=(latest.round_no + 1) if latest else 1,
                       interviewer_id=interviewer_id, scheduled_at=scheduled_at, created_by=actor_id)
    db.add(r)
    await db.flush()
    await append_event(db, candidate_id=a.candidate_id, event_type=__import__("app.models", fromlist=["CandidateEventType"]).CandidateEventType.status_changed,
                       title=f"安排第 {r.round_no} 轮面试", detail={"assignment_id": assignment_id, "round_id": r.id},
                       actor_id=actor_id)
    return r


async def submit_feedback(db: AsyncSession, *, round_id: int, score: int, conclusion: str,
                          comment: str, actor_id: int) -> InterviewRound:
    """提交反馈（I-3）：score 1-5；conclusion 枚举；history 保留旧值；feedback_at=now。"""
    r = await _visible_round(db, round_id)
    if not (isinstance(score, int) and 1 <= score <= 5):
        raise InterviewError("评分必须为 1-5")
    try:
        concl = FeedbackConclusion(conclusion)
    except ValueError:
        raise InterviewError(f"非法结论: {conclusion}") from None
    if not comment:
        raise InterviewError("评语必填")
    history = list(r.feedback_history or [])
    if r.conclusion is not None or r.score is not None:
        history.append({"score": r.score, "conclusion": r.conclusion.value if r.conclusion else None, "comment": r.comment})
    r.score, r.conclusion, r.comment = score, concl, comment
    r.feedback_history = history
    from datetime import UTC, datetime
    r.feedback_at = datetime.now(UTC)
    return r


async def ai_summarize(db: AsyncSession, *, round_id: int, llm, actor_id: int) -> InterviewRound:
    """AI 总结（I-4）：评语 → {advantages, risks, suggestions}；comment 保留。"""
    r = await _visible_round(db, round_id)
    if not r.comment:
        raise InterviewError("评语为空，无法总结")
    system = "你是招聘面试反馈总结助手。把面试官自由评语归纳为结构化 JSON。输出 {\"advantages\": [...], \"risks\": [...], \"suggestions\": [...], \"reason\": \"...\"}，均为字符串数组。"
    raw = await llm.chat_json(system, r.comment, {})
    summary = {
        "advantages": raw.get("advantages") or [],
        "risks": raw.get("risks") or [],
        "suggestions": raw.get("suggestions") or [],
    }
    r.ai_summary = summary
    return r


async def list_rounds(db: AsyncSession, assignment_id: int) -> list[dict]:
    rows = (await db.execute(select(InterviewRound).where(
        InterviewRound.assignment_id == assignment_id).order_by(InterviewRound.round_no))).scalars().all()
    return [{
        "round_id": r.id, "round_no": r.round_no, "interviewer_id": r.interviewer_id,
        "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
        "score": r.score, "conclusion": r.conclusion.value if r.conclusion else None,
        "comment": r.comment, "ai_summary": r.ai_summary,
        "feedback_at": r.feedback_at.isoformat() if r.feedback_at else None,
    } for r in rows]


async def list_overdue(db: AsyncSession, *, workspace_id: int, interviewer_id: int) -> list[dict]:
    """超时待办（I-5）：当前用户为面试官、scheduled_at+48h<now 且无反馈；只读查询天然幂等。"""
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(hours=48)
    rows = (await db.execute(select(InterviewRound).where(
        InterviewRound.workspace_id == workspace_id,
        InterviewRound.interviewer_id == interviewer_id,
        InterviewRound.feedback_at.isnull(),
        InterviewRound.scheduled_at < cutoff))).scalars().all()
    return [{"round_id": r.id, "assignment_id": r.assignment_id, "round_no": r.round_no,
             "scheduled_at": r.scheduled_at.isoformat()} for r in rows]
```

`backend/app/services/assignment_service.py` 的 `transition` 中，目标 `screen_passed` 校验旁追加两处闸门（I-2）：

```python
    if target is AssignmentStatus.offer:
        if job.hc_filled + job.hc_reserved >= job.headcount:
            raise AssignmentError("HC 已满，无法发 offer")
        if job.status is not JobStatus.open:
            raise AssignmentError("职位已关闭，不可进入 offer")
        # F14 闸门：当前轮反馈须 recommend 且完整
        from app.models import FeedbackConclusion, InterviewRound
        rounds = (await db.execute(select(InterviewRound).where(
            InterviewRound.assignment_id == assignment.id))).scalars().all()
        latest = rounds[-1] if rounds else None
        if latest is None or latest.conclusion is not FeedbackConclusion.recommend or not latest.comment:
            raise AssignmentError("当前面试轮反馈须为 recommend 且评语完整才可发 offer")
    if target is AssignmentStatus.interviewing:
        from app.models import InterviewRound
        cnt = (await db.execute(select(InterviewRound.id).where(
            InterviewRound.assignment_id == assignment.id).limit(1))).scalar_one_or_none()
        if cnt is None:
            raise AssignmentError("需先安排面试才能进入面试中")
```

- [x] **步骤 4：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_interview.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/services/interview_service.py backend/app/services/assignment_service.py backend/tests/test_interview.py
git commit -m "feat: add interview scheduling feedback summarize and state gates (P8 F14)"
```

---

### 任务 3：面试 API

**文件：**
- 创建：`backend/app/api/interviews.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_interviews_api.py`

**验收（I-4/I-6）：** 安排/反馈/AI 总结/多轮列表/overdue；member+；跨工作区 404。

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_interviews_api.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_interview_rounds_api(monkeypatch):
    from datetime import UTC, datetime

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"advantages": ["技术"], "risks": [], "suggestions": ["补沟通"]}

    async def fake_get_llm(db, ws):
        return FakeLLM()

    monkeypatch.setattr("app.api.interviews._get_llm", fake_get_llm)

    from app.core.database import SessionLocal
    from app.models import (
        Assignment, AssignmentStatus, Candidate, CandidateStatus, Job, User, Workspace,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "iv-api@b.com", "password": "secret123", "nickname": "I"})
        token = (await c.post("/api/v1/auth/login", json={"email": "iv-api@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IV-API-WS"}, headers=h)).json()["id"]
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
            my_id = (await db.execute(__import__("sqlalchemy").select(User.id).where(User.email == "iv-api@b.com"))).scalar_one()
            await db.commit()
        a_id = (await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/assignments", headers=h,
                             json={"candidate_id": cand_id})).json()["assignment_id"]
        for s in ("screen_passed",):
            await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=h, json={"to_state": s})
        # 未安排面试 → interviewing 400
        r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=h,
                         json={"to_state": "interviewing"})
        assert r.status_code == 400
        # 安排面试
        r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/interview-rounds", headers=h,
                         json={"interviewer_id": my_id, "scheduled_at": datetime.now(UTC).isoformat()})
        assert r.status_code == 200
        round_id = r.json()["round_id"]
        # 进入 interviewing
        r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=h,
                         json={"to_state": "interviewing"})
        assert r.status_code == 200
        # 反馈 hold → offer 400
        await c.post(f"/api/v1/workspaces/{ws_id}/interview-rounds/{round_id}/feedback", headers=h,
                     json={"score": 3, "conclusion": "hold", "comment": "待定"})
        r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=h,
                         json={"to_state": "offer"})
        assert r.status_code == 400
        # recommend + AI 总结 → offer 通过
        await c.post(f"/api/v1/workspaces/{ws_id}/interview-rounds/{round_id}/feedback", headers=h,
                     json={"score": 5, "conclusion": "recommend", "comment": "推荐"})
        r = await c.post(f"/api/v1/workspaces/{ws_id}/interview-rounds/{round_id}/summarize", headers=h)
        assert r.status_code == 200
        assert r.json()["ai_summary"]["advantages"] == ["技术"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=h,
                         json={"to_state": "offer"})
        assert r.status_code == 200
        # 多轮列表
        r = await c.get(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/interview-rounds", headers=h)
        assert r.status_code == 200 and len(r.json()["items"]) == 1
```

- [x] **步骤 2：运行测试验证失败**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_interviews_api.py -v`
预期：FAIL 404（路由不存在）

- [x] **步骤 3：实现面试 API**

```python
# backend/app/api/interviews.py
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Assignment, ModelConfig, User, WorkspaceMember

router = APIRouter(prefix="/api/v1", tags=["interviews"])


async def _member_info(db: AsyncSession, ws_id: int, user_id: int) -> WorkspaceMember:
    row = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "资源不存在")
    return row


async def _visible_assignment(db: AsyncSession, ws_id: int, assignment_id: int) -> Assignment:
    a = await db.get(Assignment, assignment_id)
    if a is None or a.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    return a


async def _get_llm(db: AsyncSession, ws_id: int):
    from app.services.crypto import decrypt_secret
    from app.services.model_client import LLMClient

    cfg = (await db.execute(select(ModelConfig).where(
        ModelConfig.workspace_id == ws_id, ModelConfig.model_type == "llm"))).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(502, "工作区未配置 LLM 模型，无法生成面试总结")
    return LLMClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


class ScheduleRoundRequest(BaseModel):
    interviewer_id: int
    scheduled_at: datetime


@router.post("/workspaces/{ws_id}/assignments/{assignment_id}/interview-rounds")
async def schedule_round_endpoint(ws_id: int, assignment_id: int, body: ScheduleRoundRequest,
                                  user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    await _visible_assignment(db, ws_id, assignment_id)
    from app.services.interview_service import InterviewError, schedule_round
    try:
        r = await schedule_round(db, workspace_id=ws_id, assignment_id=assignment_id,
                                 interviewer_id=body.interviewer_id, scheduled_at=body.scheduled_at,
                                 actor_id=user.id)
    except InterviewError as exc:
        raise HTTPException(400, str(exc))
    await db.commit()
    return {"round_id": r.id, "round_no": r.round_no}


class FeedbackRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)
    conclusion: str
    comment: str = Field(..., min_length=1, max_length=2000)


@router.post("/workspaces/{ws_id}/interview-rounds/{round_id}/feedback")
async def submit_feedback_endpoint(ws_id: int, round_id: int, body: FeedbackRequest,
                                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    from app.services.interview_service import InterviewError, submit_feedback
    try:
        r = await submit_feedback(db, round_id=round_id, score=body.score,
                                  conclusion=body.conclusion, comment=body.comment, actor_id=user.id)
    except InterviewError as exc:
        raise HTTPException(400, str(exc))
    if r.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    await db.commit()
    return {"round_id": r.id, "conclusion": r.conclusion.value, "score": r.score}


@router.post("/workspaces/{ws_id}/interview-rounds/{round_id}/summarize")
async def summarize_endpoint(ws_id: int, round_id: int,
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    from app.services.interview_service import InterviewError, ai_summarize
    try:
        llm = await _get_llm(db, ws_id)
        r = await ai_summarize(db, round_id=round_id, llm=llm, actor_id=user.id)
    except InterviewError as exc:
        raise HTTPException(400, str(exc))
    if r.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    await db.commit()
    return {"round_id": r.id, "ai_summary": r.ai_summary, "comment": r.comment}


@router.get("/workspaces/{ws_id}/assignments/{assignment_id}/interview-rounds")
async def list_rounds_endpoint(ws_id: int, assignment_id: int,
                               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    await _visible_assignment(db, ws_id, assignment_id)
    from app.services.interview_service import list_rounds
    return {"items": await list_rounds(db, assignment_id)}


@router.get("/workspaces/{ws_id}/interviews/overdue")
async def overdue_endpoint(ws_id: int,
                           user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    from app.services.interview_service import list_overdue
    items = await list_overdue(db, workspace_id=ws_id, interviewer_id=user.id)
    return {"items": items}
```

`backend/app/main.py`：`from app.api import interviews` + `app.include_router(interviews.router)`。

- [x] **步骤 4：运行测试验证通过**

运行：`../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests/test_interviews_api.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app/api/interviews.py backend/app/main.py backend/tests/test_interviews_api.py
git commit -m "feat: add interview round scheduling feedback and summary endpoints (P8 F14)"
```

---

### 任务 4：前端面试操作

**文件：**
- 创建：`frontend/src/api/interviews.ts`
- 修改：`frontend/src/pages/JobDetailPage.tsx`

- [x] **步骤 1：API 客户端**

```ts
// frontend/src/api/interviews.ts
import { client } from "./client";

export async function scheduleRound(wsId: number, assignmentId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/assignments/${assignmentId}/interview-rounds`, body).then((r) => r.data);
}
export async function submitFeedback(wsId: number, roundId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/interview-rounds/${roundId}/feedback`, body).then((r) => r.data);
}
export async function summarizeRound(wsId: number, roundId: number) {
  return client.post(`/workspaces/${wsId}/interview-rounds/${roundId}/summarize`).then((r) => r.data);
}
export async function listRounds(wsId: number, assignmentId: number) {
  return client.get(`/workspaces/${wsId}/assignments/${assignmentId}/interview-rounds`).then((r) => r.data);
}
```

- [x] **步骤 2：职位详情 interviewing 组加面试操作**

`frontend/src/pages/JobDetailPage.tsx`：`interviewing` 状态的行加「安排面试」（prompt 输入面试官 ID）与「提交反馈」（prompt 输入评分/结论/评语 JSON）两个按钮；反馈后显示 AI 总结按钮。其余状态操作不变。

- [x] **步骤 3：构建与测试**

```bash
cd frontend && npm install && npm run build && npx vitest run
```

预期：通过

- [x] **步骤 4：Commit**

```bash
git add frontend/src/api/interviews.ts frontend/src/pages/JobDetailPage.tsx
git commit -m "feat: add interview scheduling and feedback UI (P8 F14)"
```

---

### 任务 5：回归验证与台账

- [x] **步骤 1：全量回归**

```bash
export MODEL_KEY_ENC_KEY="..." && export JWT_SECRET="..." && export DATABASE_URL="..."
../.worktrees/p2-resume-parsing/.venv/bin/pytest backend/tests -q
```

预期：全量通过（main 249 + P8 新增全部）

- [x] **步骤 2：静态检查**

```bash
../.worktrees/p2-resume-parsing/.venv/bin/ruff check backend/app backend/tests && git diff --check
```

- [x] **步骤 3：更新台账**

在 `docs/superpowers/deviation-log.md` 追加 §16「P8 面试安排与反馈闭环（F14）实现与偏离」，记录 I-1~I-7 裁决与验证。

- [x] **步骤 4：勾选计划并提交**

```bash
git add -A && git commit -m "docs: 记录 P8 面试反馈实现偏差与验证（P8 F14）"
```

---

## 自检

**1. 规格覆盖度：**

| 需求 | 对应任务 |
|------|---------|
| 每轮独立 interview_round（轮次/面试官/时间） | 任务 1、2、3 |
| 结构化反馈（评分/结论/评语）多轮逐轮 + 历史保留 | 任务 1、2、3 |
| recommend 才可发 offer、advance 显式安排下一轮 | 任务 2（闸门） |
| 面试安排完成才可进入 interviewing | 任务 2（闸门） |
| 反馈 AI 总结（优势/风险/建议，保留原始评语） | 任务 2、3 |
| 48h 超时待办提醒（round_id 幂等） | 任务 2、3 |
| 面试官须为工作区成员、member+ 权限 | 任务 2、3 |
| 前端安排/反馈/AI 总结 | 任务 4 |

**2. 占位符扫描：** 无 TODO/占位；`schedule_round`/`submit_feedback`/`ai_summarize`/`list_rounds`/`list_overdue` 在任务 2 定义、任务 3 API 消费一致；`_get_llm` 在任务 3 定义；`FeedbackConclusion` 在任务 1 定义、任务 2/3 一致。

**3. 类型一致性：** `transition` 闸门在任务 2 改 `assignment_service.py`，P7 既有测试（`test_assignment.py`/`test_assignments_api.py`）中用 `transition(... "interviewing"/"offer")` 的用例会被新闸门影响——需同步这些用例（先安排面试/提交 recommend 反馈再流转）。任务 2 步骤 4 须同时跑 `test_assignment.py` 确认。

**已知边界（后续处理）：** 面试日历集成（P2 预留）；反馈 AI 总结的编辑（MVP 为覆盖重生成，历史在 feedback_history）；超时提醒推送渠道（V1.1）；F15 查重联动提示（已由 pending_review + merge + 指派历史覆盖路径）；F11 统计查询。
