import pytest


@pytest.mark.asyncio
async def test_interview_round_roundtrip():
    from app.core.database import SessionLocal
    from app.models import (
        Assignment,
        AssignmentStatus,
        Candidate,
        CandidateStatus,
        FeedbackConclusion,
        InterviewRound,
        Job,
        User,
        Workspace,
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

class FakeLLM:
    async def chat_json(self, system, user, schema):
        return {"advantages": ["技术扎实"], "risks": ["沟通一般"], "suggestions": ["补充团队协作题"]}


@pytest.mark.asyncio
async def test_schedule_feedback_summarize_and_overdue():
    from datetime import UTC, datetime, timedelta

    from app.core.database import SessionLocal
    from app.models import (
        Assignment,
        AssignmentStatus,
        Candidate,
        CandidateStatus,
        FeedbackConclusion,
        Job,
        User,
        Workspace,
    )
    from app.services.interview_service import (
        InterviewError,
        ai_summarize,
        list_overdue,
        schedule_round,
        submit_feedback,
    )

    async with SessionLocal() as db:
        owner = User(email="irv2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="irv2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        from app.models import WorkspaceMember, WorkspaceRole
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.owner))
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
        with pytest.raises(InterviewError, match="上一轮反馈"):
            await schedule_round(db, workspace_id=ws_id, assignment_id=a_id,
                                 interviewer_id=owner.id, scheduled_at=datetime.now(UTC), actor_id=owner.id)
        r1 = await submit_feedback(db, round_id=r1.id, score=4, conclusion="advance",
                                   comment="技术不错", actor_id=owner.id)
        r2 = await schedule_round(db, workspace_id=ws_id, assignment_id=a_id,
                                  interviewer_id=owner.id, scheduled_at=datetime.now(UTC), actor_id=owner.id)
        assert r2.round_no == 2  # round_no 递增
        assert r1.score == 4 and r1.feedback_history == []  # 首次反馈为当前值
        r1 = await submit_feedback(db, round_id=r1.id, score=5, conclusion="recommend",
                                   comment="推荐", actor_id=owner.id)
        assert len(r1.feedback_history) == 1  # 旧值入历史
        assert r1.feedback_history[0]["comment"] == "技术不错"
        assert r1.conclusion is FeedbackConclusion.recommend
        r1 = await ai_summarize(db, round_id=r1.id, llm=FakeLLM(), actor_id=owner.id)
        assert r1.ai_summary["advantages"] == ["技术扎实"]
        assert r1.comment == "推荐"  # 原始评语保留
        r2.scheduled_at = datetime.now(UTC) - timedelta(days=2)
        await db.commit()
        overdue = await list_overdue(db, workspace_id=ws_id, interviewer_id=owner.id)
        assert any(o["round_id"] == r2.id for o in overdue)


@pytest.mark.asyncio
async def test_transition_gates_interviewing_and_offer():
    from datetime import UTC, datetime

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
    from app.services.interview_service import schedule_round, submit_feedback

    async with SessionLocal() as db:
        owner = User(email="gate-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="gate-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        from app.models import WorkspaceMember, WorkspaceRole
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.owner))
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
