import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_assign_batch_and_board():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, Job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "as-api@b.com", "password": "secret123", "nickname": "A"})
        token = (await c.post("/api/v1/auth/login", json={"email": "as-api@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "AS-API-WS"}, headers=h)).json()["id"]
        async with SessionLocal() as db:
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=5)
            job2 = Job(workspace_id=ws_id, name="测试岗", description="", headcount=5)
            db.add_all([job, job2])
            await db.flush()
            job_id, job2_id = job.id, job2.id
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
        # 重复指派同一职位 → 干净 400（非 409）
        r_dup = await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/assignments", headers=h,
                             json={"candidate_id": cand_ids[0], "idempotency_key": "api-dup"})
        assert r_dup.status_code == 400
        # 批量（新职位）
        r3 = await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job2_id}/assignments/batch", headers=h,
                          json={"candidate_ids": cand_ids, "idempotency_key": "api-b1"})
        assert r3.status_code == 200
        assert len(r3.json()["items"]) >= 2
        # 看板（批量职位 job2 应有 2 条 pending_screen；job1 有 1 条）
        r4 = await c.get(f"/api/v1/workspaces/{ws_id}/jobs/{job2_id}/board", headers=h)
        assert r4.status_code == 200
        assert len(r4.json()["groups"]["pending_screen"]) >= 2
        r4b = await c.get(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/board", headers=h)
        assert len(r4b.json()["groups"]["pending_screen"]) == 1
        # 候选指派历史
        r5 = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_ids[0]}/assignments", headers=h)
        assert r5.status_code == 200 and r5.json()["items"]

@pytest.mark.asyncio
async def test_transition_and_hire_api():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, Job

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
        # 正常流转到 interviewing（先插一轮 recommend 面试轮供 F14 闸门）
        from datetime import UTC, datetime

        from app.core.database import SessionLocal
        from app.models import FeedbackConclusion, InterviewRound, User
        async with SessionLocal() as db:
            my_id = (await db.execute(__import__("sqlalchemy").select(User.id).where(User.email == "as-t@b.com"))).scalar_one()
            db.add(InterviewRound(workspace_id=ws_id, assignment_id=a_id, round_no=1,
                                  interviewer_id=my_id, scheduled_at=datetime.now(UTC),
                                  score=5, conclusion=FeedbackConclusion.recommend, comment="推荐",
                                  feedback_at=datetime.now(UTC)))
            await db.commit()
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


@pytest.mark.asyncio
async def test_closed_by_job_admin_only():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, Job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "cb-owner@b.com", "password": "secret123", "nickname": "O"})
        ot = (await c.post("/api/v1/auth/login", json={"email": "cb-owner@b.com", "password": "secret123"})).json()["access_token"]
        oh = {"Authorization": f"Bearer {ot}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "CB-WS"}, headers=oh)).json()["id"]
        async with SessionLocal() as db:
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=3)
            db.add(job)
            await db.flush()
            job_id = job.id
            cand = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                             structured_data={}, search_text="")
            db.add(cand)
            await db.flush()
            await db.commit()
            cand_id = cand.id
        a_id = (await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/assignments", headers=oh,
                             json={"candidate_id": cand_id})).json()["assignment_id"]
        # 邀请 member
        await c.post("/api/v1/auth/register", json={"email": "cb-mem@b.com", "password": "secret123", "nickname": "M"})
        mt = (await c.post("/api/v1/auth/login", json={"email": "cb-mem@b.com", "password": "secret123"})).json()["access_token"]
        mh = {"Authorization": f"Bearer {mt}"}
        await c.post(f"/api/v1/workspaces/{ws_id}/members", headers=oh, json={"email": "cb-mem@b.com", "role": "member"})
        # member 403
        r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=mh,
                         json={"to_state": "closed_by_job", "close_reason": "x"})
        assert r.status_code == 403
        async with SessionLocal() as db:
            from app.models import JobStatus
            job = await db.get(Job, job_id)
            job.status = JobStatus.closed
            await db.commit()
        # admin 成功
        r = await c.post(f"/api/v1/workspaces/{ws_id}/assignments/{a_id}/transition", headers=oh,
                         json={"to_state": "closed_by_job", "close_reason": "职位终止"})
        assert r.status_code == 200
        assert r.json()["status"] == "closed_by_job"


@pytest.mark.asyncio
async def test_member_cannot_read_hired_assignment_history_or_board():
    from app.core.database import SessionLocal
    from app.models import Assignment, AssignmentStatus, Candidate, CandidateStatus, Job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "acl-owner@b.com", "password": "secret123", "nickname": "O"})
        owner_token = (await c.post("/api/v1/auth/login", json={"email": "acl-owner@b.com", "password": "secret123"})).json()["access_token"]
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "ACL-WS"}, headers=owner_headers)).json()["id"]
        await c.post("/api/v1/auth/register", json={"email": "acl-member@b.com", "password": "secret123", "nickname": "M"})
        member_token = (await c.post("/api/v1/auth/login", json={"email": "acl-member@b.com", "password": "secret123"})).json()["access_token"]
        member_headers = {"Authorization": f"Bearer {member_token}"}
        await c.post(f"/api/v1/workspaces/{ws_id}/members", headers=owner_headers,
                     json={"email": "acl-member@b.com", "role": "member"})

        async with SessionLocal() as db:
            from sqlalchemy import select

            from app.models import User

            owner_id = (await db.execute(select(User.id).where(User.email == "acl-owner@b.com"))).scalar_one()
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=1)
            candidate = Candidate(workspace_id=ws_id, status=CandidateStatus.hired, name="员工",
                                  structured_data={}, search_text="")
            db.add_all([job, candidate])
            await db.flush()
            assignment = Assignment(workspace_id=ws_id, candidate_id=candidate.id, job_id=job.id,
                                    status=AssignmentStatus.hired, created_by=owner_id)
            db.add(assignment)
            await db.commit()
            job_id, candidate_id = job.id, candidate.id

        board = await c.get(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/board", headers=member_headers)
        assert board.status_code == 200
        assert all(item["candidate_id"] != candidate_id for items in board.json()["groups"].values() for item in items)
        history = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{candidate_id}/assignments", headers=member_headers)
        assert history.status_code == 404


@pytest.mark.asyncio
async def test_assign_cross_workspace_candidate_returns_404():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, Job

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "xw-owner@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "xw-owner@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_a = (await c.post("/api/v1/workspaces", json={"name": "XW-A"}, headers=h)).json()["id"]
        ws_b = (await c.post("/api/v1/workspaces", json={"name": "XW-B"}, headers=h)).json()["id"]
        async with SessionLocal() as db:
            job = Job(workspace_id=ws_a, name="后端", description="", headcount=5)
            db.add(job)
            await db.flush()
            job_id = job.id
            foreign = Candidate(workspace_id=ws_b, status=CandidateStatus.active, name="外组",
                                structured_data={}, search_text="")
            db.add(foreign)
            await db.flush()
            foreign_id = foreign.id
            await db.commit()

        single = await c.post(f"/api/v1/workspaces/{ws_a}/jobs/{job_id}/assignments", headers=h,
                              json={"candidate_id": foreign_id, "idempotency_key": "xw-1"})
        assert single.status_code == 404
        batch = await c.post(f"/api/v1/workspaces/{ws_a}/jobs/{job_id}/assignments/batch", headers=h,
                             json={"candidate_ids": [foreign_id], "idempotency_key": "xw-2"})
        assert batch.status_code == 200
        assert batch.json()["items"][0]["error"] == "资源不存在"
