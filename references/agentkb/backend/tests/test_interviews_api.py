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
    from app.models import Candidate, CandidateStatus, Job, User

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "iv-api@b.com", "password": "secret123", "nickname": "I"})
        token = (await c.post("/api/v1/auth/login", json={"email": "iv-api@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IV-API-WS"}, headers=h)).json()["id"]
        async with SessionLocal() as db:
            from sqlalchemy import select
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=3)
            db.add(job)
            await db.flush()
            job_id = job.id
            cand = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                             structured_data={}, search_text="")
            db.add(cand)
            await db.flush()
            cand_id = cand.id
            my_id = (await db.execute(select(User.id).where(User.email == "iv-api@b.com"))).scalar_one()
            await db.commit()
        a_id = (await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/assignments", headers=h,
                             json={"candidate_id": cand_id})).json()["assignment_id"]
        await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=h,
                     json={"to_state": "screen_passed"})
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

@pytest.mark.asyncio
async def test_interview_cross_workspace_and_validation():
    from datetime import UTC, datetime

    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateStatus,
        InterviewRound,
        Job,
        User,
        Workspace,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "iv2@b.com", "password": "secret123", "nickname": "I2"})
        token = (await c.post("/api/v1/auth/login", json={"email": "iv2@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws1 = (await c.post("/api/v1/workspaces", json={"name": "IV2-WS1"}, headers=h)).json()["id"]
        await c.post("/api/v1/workspaces", json={"name": "IV2-WS2"}, headers=h)
        async with SessionLocal() as db:
            from sqlalchemy import select
            my_id = (await db.execute(select(User.id).where(User.email == "iv2@b.com"))).scalar_one()
            # 在 ws2 建一个 round
            owner2 = User(email="iv2-owner2@b.com", hashed_password="x", nickname="o2")
            db.add(owner2)
            await db.flush()
            w2 = Workspace(name="iv2-ws2-owner", owner_id=owner2.id)
            db.add(w2)
            await db.flush()
            cand = Candidate(workspace_id=w2.id, status=CandidateStatus.active, name="张三",
                             structured_data={}, search_text="")
            job = Job(workspace_id=w2.id, name="后端", description="", headcount=1)
            db.add_all([cand, job])
            await db.flush()
            from app.models import Assignment, AssignmentStatus
            a = Assignment(workspace_id=w2.id, candidate_id=cand.id, job_id=job.id,
                           status=AssignmentStatus.interviewing)
            db.add(a)
            await db.flush()
            r = InterviewRound(workspace_id=w2.id, assignment_id=a.id, round_no=1,
                               interviewer_id=my_id, scheduled_at=datetime.now(UTC))
            db.add(r)
            await db.commit()
            round_id = r.id
        # 通过 ws1 访问 ws2 的 round → 404（不泄露存在性）
        r = await c.post(f"/api/v1/workspaces/{ws1}/interview-rounds/{round_id}/feedback", headers=h,
                         json={"score": 3, "conclusion": "hold", "comment": "x"})
        assert r.status_code == 404
        r = await c.post(f"/api/v1/workspaces/{ws1}/interview-rounds/{round_id}/summarize", headers=h)
        assert r.status_code == 404
        # 伪造不存在 round → 404
        r = await c.post(f"/api/v1/workspaces/{ws1}/interview-rounds/999999/feedback", headers=h,
                         json={"score": 3, "conclusion": "hold", "comment": "x"})
        assert r.status_code == 404
        # 非法结论 → 400
        async with SessionLocal() as db:
            from sqlalchemy import select
            my_id = (await db.execute(select(User.id).where(User.email == "iv2@b.com"))).scalar_one()
            cand2 = Candidate(workspace_id=ws1, status=CandidateStatus.active, name="李四",
                              structured_data={}, search_text="")
            job2 = Job(workspace_id=ws1, name="前端", description="", headcount=1)
            db.add_all([cand2, job2])
            await db.flush()
            from app.models import Assignment, AssignmentStatus
            a2 = Assignment(workspace_id=ws1, candidate_id=cand2.id, job_id=job2.id,
                            status=AssignmentStatus.interviewing)
            db.add(a2)
            await db.flush()
            r2 = InterviewRound(workspace_id=ws1, assignment_id=a2.id, round_no=1,
                                interviewer_id=my_id, scheduled_at=datetime.now(UTC))
            db.add(r2)
            await db.flush()
            ws1_round = r2.id
            await db.commit()
        r = await c.post(f"/api/v1/workspaces/{ws1}/interview-rounds/{ws1_round}/feedback", headers=h,
                         json={"score": 3, "conclusion": "nonsense", "comment": "x"})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_member_cannot_read_hired_interview_rounds():
    from datetime import UTC, datetime

    from app.core.database import SessionLocal
    from app.models import (
        Assignment,
        AssignmentStatus,
        Candidate,
        CandidateStatus,
        InterviewRound,
        Job,
        User,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "iv-acl-owner@b.com", "password": "secret123", "nickname": "O"})
        owner_token = (await c.post("/api/v1/auth/login", json={"email": "iv-acl-owner@b.com", "password": "secret123"})).json()["access_token"]
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IV-ACL-WS"}, headers=owner_headers)).json()["id"]
        await c.post("/api/v1/auth/register", json={"email": "iv-acl-member@b.com", "password": "secret123", "nickname": "M"})
        member_token = (await c.post("/api/v1/auth/login", json={"email": "iv-acl-member@b.com", "password": "secret123"})).json()["access_token"]
        member_headers = {"Authorization": f"Bearer {member_token}"}
        await c.post(f"/api/v1/workspaces/{ws_id}/members", headers=owner_headers,
                     json={"email": "iv-acl-member@b.com", "role": "member"})
        async with SessionLocal() as db:
            owner_id = (await db.execute(__import__("sqlalchemy").select(User.id).where(User.email == "iv-acl-owner@b.com"))).scalar_one()
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=1)
            candidate = Candidate(workspace_id=ws_id, status=CandidateStatus.hired, name="员工",
                                  structured_data={}, search_text="")
            db.add_all([job, candidate])
            await db.flush()
            assignment = Assignment(workspace_id=ws_id, candidate_id=candidate.id, job_id=job.id,
                                    status=AssignmentStatus.hired, created_by=owner_id)
            db.add(assignment)
            await db.flush()
            round_ = InterviewRound(workspace_id=ws_id, assignment_id=assignment.id, round_no=1,
                                    interviewer_id=owner_id, scheduled_at=datetime.now(UTC))
            db.add(round_)
            await db.commit()
            assignment_id = assignment.id
        response = await c.get(f"/api/v1/workspaces/{ws_id}/assignments/{assignment_id}/interview-rounds",
                               headers=member_headers)
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_interview_result_api_and_offer_rejection():
    from app.core.database import SessionLocal
    from app.models import Assignment, AssignmentStatus, Candidate, CandidateStatus, Job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "iv-result@b.com", "password": "secret123", "nickname": "I"})
        token = (await c.post("/api/v1/auth/login", json={"email": "iv-result@b.com", "password": "secret123"})).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IV-RESULT-WS"}, headers=headers)).json()["id"]
        async with SessionLocal() as db:
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=3)
            candidate = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="结果候选人",
                                  structured_data={}, search_text="")
            db.add_all([job, candidate])
            await db.flush()
            assignment = Assignment(workspace_id=ws_id, candidate_id=candidate.id, job_id=job.id,
                                    status=AssignmentStatus.interviewing)
            db.add(assignment)
            await db.commit()
            assignment_id, job_id = assignment.id, job.id

        response = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{assignment_id}/interview-result",
                                headers=headers, json={"result": "no_show"})
        assert response.status_code == 200
        assert response.json()["interview_result"] == "no_show"

        response = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{assignment_id}/interview-result",
                                headers=headers, json={"result": "cancelled"})
        assert response.status_code == 200
        async with SessionLocal() as db:
            stored = await db.get(Assignment, assignment_id)
            assert stored.interview_result.value == "cancelled"
            stored.status = AssignmentStatus.offer
            job = await db.get(Job, job_id)
            job.hc_reserved = 1
            await db.commit()

        response = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{assignment_id}/transition",
                                headers=headers, json={"to_state": "offer_rejected"})
        assert response.status_code == 200
        async with SessionLocal() as db:
            stored = await db.get(Assignment, assignment_id)
            job = await db.get(Job, job_id)
            assert stored.status is AssignmentStatus.offer_rejected
            assert job.hc_reserved == 0


@pytest.mark.asyncio
async def test_failed_interview_result_rejects_assignment():
    from app.core.database import SessionLocal
    from app.models import Assignment, AssignmentStatus, Candidate, CandidateStatus, Job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "iv-failed@b.com", "password": "secret123", "nickname": "I"})
        token = (await c.post("/api/v1/auth/login", json={"email": "iv-failed@b.com", "password": "secret123"})).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IV-FAILED-WS"}, headers=headers)).json()["id"]
        async with SessionLocal() as db:
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=1)
            candidate = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="淘汰候选人",
                                  structured_data={}, search_text="")
            db.add_all([job, candidate])
            await db.flush()
            assignment = Assignment(workspace_id=ws_id, candidate_id=candidate.id, job_id=job.id,
                                    status=AssignmentStatus.interviewing)
            db.add(assignment)
            await db.commit()
            assignment_id, candidate_id = assignment.id, candidate.id

        response = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{assignment_id}/interview-result",
                                headers=headers, json={"result": "failed", "reason": "技术不匹配"})
        assert response.status_code == 200
        async with SessionLocal() as db:
            assignment = await db.get(Assignment, assignment_id)
            candidate = await db.get(Candidate, candidate_id)
            assert assignment.status is AssignmentStatus.rejected
            assert assignment.interview_result.value == "failed"
            assert candidate.status is CandidateStatus.rejected
