import pytest


@pytest.mark.asyncio
async def test_assignment_model_roundtrip():
    from app.core.database import SessionLocal
    from app.models import (
        Assignment,
        AssignmentStatus,
        Candidate,
        CandidateStatus,
        Job,
        User,
        Workspace,
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

@pytest.mark.asyncio
async def _offer_ready_round(db, workspace_id: int, assignment_id: int, interviewer_id: int) -> None:
    """直接插一轮 recommend 反馈的面试轮，供 F14 闸门通过（绕过 schedule_round 的成员校验）。"""
    from datetime import UTC, datetime

    from app.models import FeedbackConclusion, InterviewRound
    r = InterviewRound(workspace_id=workspace_id, assignment_id=assignment_id, round_no=1,
                       interviewer_id=interviewer_id, scheduled_at=datetime.now(UTC),
                       score=5, conclusion=FeedbackConclusion.recommend, comment="推荐",
                       feedback_at=datetime.now(UTC))
    db.add(r)
    await db.flush()



async def test_transition_matrix_and_terminal():
    from app.core.database import SessionLocal
    from app.models import (
        AssignmentStatus,
        Candidate,
        CandidateStatus,
        Job,
        User,
        Workspace,
    )
    from app.services.assignment_service import (
        AssignmentError,
        create_assignment,
        transition,
    )

    async with SessionLocal() as db:
        owner = User(email="asm-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="asm-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        job1 = Job(workspace_id=ws.id, name="后端", description="", headcount=3)
        job2 = Job(workspace_id=ws.id, name="测试", description="", headcount=3)
        db.add_all([cand, job1, job2])
        await db.commit()
        ws_id, cand_id = ws.id, cand.id

    async with SessionLocal() as db:
        a = await create_assignment(db, workspace_id=ws_id, candidate_id=cand_id, job_id=job1.id,
                                    idempotency_key="t1", actor_id=owner.id)
        assert a.status is AssignmentStatus.pending_screen
        # 非法跳转（pending_screen → offer 不允许）
        bad = await create_assignment(db, workspace_id=ws_id, candidate_id=cand_id, job_id=job2.id,
                                      idempotency_key="t-bad", actor_id=owner.id)
        with pytest.raises(AssignmentError, match="不允许"):
            await transition(db, assignment=bad, to_state="offer", actor_id=owner.id)
        # 顺序流转
        a = await transition(db, assignment=a, to_state="screen_passed", actor_id=owner.id)
        assert a.status is AssignmentStatus.screen_passed
        await _offer_ready_round(db, ws_id, a.id, owner.id)
        a = await transition(db, assignment=a, to_state="interviewing", actor_id=owner.id)
        a = await transition(db, assignment=a, to_state="offer", actor_id=owner.id)
        assert a.status is AssignmentStatus.offer
        # C-2：transition 直达 hired 被拒（入职仅 hire() 聚合入口）
        with pytest.raises(AssignmentError, match="不允许"):
            await transition(db, assignment=a, to_state="hired", actor_id=owner.id)
        from app.services.assignment_service import hire
        a = await hire(db, assignment=a, actor_id=owner.id)
        assert a.status is AssignmentStatus.hired
        with pytest.raises(AssignmentError, match="终态"):
            await transition(db, assignment=a, to_state="rejected", actor_id=owner.id)


async def test_reject_requires_reason_and_updates_pool():
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateStatus,
        Job,
        User,
        Workspace,
    )
    from app.services.assignment_service import (
        AssignmentError,
        create_assignment,
        transition,
    )

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
        cand = await db.get(Candidate, cand_id)
        assert cand.status is CandidateStatus.rejected


@pytest.mark.asyncio
async def test_hc_occupancy_and_hire_aggregation():
    from app.core.database import SessionLocal
    from app.models import (
        Assignment,
        AssignmentStatus,
        Candidate,
        CandidateStatus,
        Job,
        User,
        Workspace,
    )
    from app.services.assignment_service import (
        AssignmentError,
        create_assignment,
        hire,
        transition,
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
        cand2 = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="李四",
                          structured_data={}, search_text="")
        job1 = Job(workspace_id=ws.id, name="后端", description="", headcount=1)
        job2 = Job(workspace_id=ws.id, name="前端", description="", headcount=1)
        db.add_all([cand, cand2, job1, job2])
        await db.commit()
        ws_id = ws.id

    async with SessionLocal() as db:
        a1 = await create_assignment(db, workspace_id=ws_id, candidate_id=cand.id, job_id=job1.id,
                                     idempotency_key="h1", actor_id=owner.id)
        a2 = await create_assignment(db, workspace_id=ws_id, candidate_id=cand.id, job_id=job2.id,
                                     idempotency_key="h2", actor_id=owner.id)
        for a in (a1, a2):
            await _offer_ready_round(db, ws_id, a.id, owner.id)
            for s in ("screen_passed", "interviewing", "offer"):
                a = await transition(db, assignment=a, to_state=s, actor_id=owner.id)
        job1 = await db.get(Job, job1.id)
        assert job1.hc_reserved == 1  # offer 占 reservation
        # job1 HC 满 → 另一候选人进 offer 被拒
        a3 = await create_assignment(db, workspace_id=ws_id, candidate_id=cand2.id, job_id=job1.id,
                                     idempotency_key="h3", actor_id=owner.id)
        await _offer_ready_round(db, ws_id, a3.id, owner.id)
        for s in ("screen_passed", "interviewing"):
            a3 = await transition(db, assignment=a3, to_state=s, actor_id=owner.id)
        with pytest.raises(AssignmentError, match="HC"):
            await transition(db, assignment=a3, to_state="offer", actor_id=owner.id)
        # 入职 a1 → 聚合关闭 a2
        a1 = await hire(db, assignment=a1, actor_id=owner.id)
        job1 = await db.get(Job, job1.id)
        job2 = await db.get(Job, job2.id)
        assert job1.hc_filled == 1 and job1.hc_reserved == 0
        assert job2.hc_reserved == 0
        a2 = await db.get(Assignment, a2.id)
        assert a2.status is AssignmentStatus.closed_after_hire
        cand = await db.get(Candidate, cand.id)
        assert cand.status is CandidateStatus.hired


@pytest.mark.asyncio
async def test_closed_by_job_and_offer_rejected_pool():
    from app.core.database import SessionLocal
    from app.models import (
        AssignmentStatus,
        Candidate,
        CandidateStatus,
        Job,
        User,
        Workspace,
    )
    from app.services.assignment_service import (
        create_assignment,
        transition,
    )

    async with SessionLocal() as db:
        owner = User(email="cbj-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cbj-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        job = Job(workspace_id=ws.id, name="后端", description="", headcount=2)
        db.add_all([cand, job])
        await db.commit()
        ws_id, cand_id, job_id = ws.id, cand.id, job.id

    async with SessionLocal() as db:
        # C-1：closed_by_job 可达（admin 关闭余下指派）
        a = await create_assignment(db, workspace_id=ws_id, candidate_id=cand_id, job_id=job_id,
                                    idempotency_key="cbj", actor_id=owner.id)
        job = await db.get(Job, job_id)
        job.status = __import__("app.models", fromlist=["JobStatus"]).JobStatus.closed
        a = await transition(db, assignment=a, to_state="closed_by_job", close_reason="职位终止", actor_id=owner.id)
        assert a.status is AssignmentStatus.closed_by_job
        # closed_by_job 保持前池（默认 active）
        cand = await db.get(Candidate, cand_id)
        assert cand.status is CandidateStatus.active
        # offer_rejected → 无其他进行中 → 池 rejected
        cand2 = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="李四",
                          structured_data={}, search_text="")
        db.add(cand2)
        await db.flush()
        job2 = Job(workspace_id=ws_id, name="前端", description="", headcount=2)
        db.add(job2)
        await db.flush()
        a2 = await create_assignment(db, workspace_id=ws_id, candidate_id=cand2.id, job_id=job2.id,
                                     idempotency_key="or", actor_id=owner.id)
        await _offer_ready_round(db, ws_id, a2.id, owner.id)
        for s in ("screen_passed", "interviewing", "offer"):
            a2 = await transition(db, assignment=a2, to_state=s, actor_id=owner.id)
        a2 = await transition(db, assignment=a2, to_state="offer_rejected", actor_id=owner.id)
        assert a2.status is AssignmentStatus.offer_rejected
        cand2 = await db.get(Candidate, cand2.id)
        assert cand2.status is CandidateStatus.rejected


@pytest.mark.asyncio
async def test_concurrent_hire_does_not_double_count_hc():
    """D-1 回归：两个 session 用陈旧 offer Assignment 并发入职，hc_filled 只 +1。"""
    import asyncio

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import (
        Assignment,
        Candidate,
        CandidateStatus,
        Job,
        User,
        Workspace,
    )
    from app.services.assignment_service import (
        create_assignment,
        hire,
        transition,
    )

    async with SessionLocal() as db:
        owner = User(email="cc-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cc-ws", owner_id=owner.id)
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
                                    idempotency_key="cc", actor_id=owner.id)
        await _offer_ready_round(db, ws_id, a.id, owner.id)
        for s in ("screen_passed", "interviewing", "offer"):
            a = await transition(db, assignment=a, to_state=s, actor_id=owner.id)
        assignment_id = a.id
        await db.commit()

    # 两个 session 各自预加载陈旧 offer Assignment（模拟并发请求到达时的快照）
    async with SessionLocal() as db_a, SessionLocal() as db_b:
        stale_a = (await db_a.execute(select(Assignment).where(
            Assignment.id == assignment_id))).scalar_one()
        stale_b = (await db_b.execute(select(Assignment).where(
            Assignment.id == assignment_id))).scalar_one()

    async def _hire_stale(session, stale):
        try:
            await hire(session, assignment=stale, actor_id=owner.id)
            await session.commit()
            return "ok"
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            return str(exc)

    async def _run_a():
        async with SessionLocal() as db2:
            return await _hire_stale(db2, stale_a)

    async def _run_b():
        async with SessionLocal() as db2:
            return await _hire_stale(db2, stale_b)

    results = await asyncio.gather(_run_a(), _run_b())
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.hc_filled == 1, f"hc_filled={job.hc_filled}, results={results}"
        assert job.hc_reserved == 0
        cand = await db.get(Candidate, cand_id)
        assert cand.status is CandidateStatus.hired


@pytest.mark.asyncio
async def test_concurrent_offer_does_not_double_reserve_hc():
    """D-1 回归：两个 session 用陈旧 interviewing Assignment 并发转 offer，hc_reserved 只 +1。"""
    import asyncio

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import (
        Assignment,
        Candidate,
        CandidateStatus,
        Job,
        User,
        Workspace,
    )
    from app.services.assignment_service import (
        create_assignment,
        transition,
    )

    async with SessionLocal() as db:
        owner = User(email="co-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="co-ws", owner_id=owner.id)
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
                                    idempotency_key="co", actor_id=owner.id)
        await _offer_ready_round(db, ws_id, a.id, owner.id)
        for s in ("screen_passed", "interviewing"):
            a = await transition(db, assignment=a, to_state=s, actor_id=owner.id)
        assignment_id = a.id
        await db.commit()

    async with SessionLocal() as db_a, SessionLocal() as db_b:
        stale_a = (await db_a.execute(select(Assignment).where(
            Assignment.id == assignment_id))).scalar_one()
        stale_b = (await db_b.execute(select(Assignment).where(
            Assignment.id == assignment_id))).scalar_one()

    async def _run(session, stale):
        try:
            await transition(db=session, assignment=stale, to_state="offer", actor_id=owner.id)
            await session.commit()
            return "ok"
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            return str(exc)

    async def _run_a():
        async with SessionLocal() as db2:
            return await _run(db2, stale_a)

    async def _run_b():
        async with SessionLocal() as db2:
            return await _run(db2, stale_b)

    results = await asyncio.gather(_run_a(), _run_b())
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.hc_reserved == 1, f"hc_reserved={job.hc_reserved}, results={results}"
