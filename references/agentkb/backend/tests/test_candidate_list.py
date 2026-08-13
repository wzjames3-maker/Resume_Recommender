import pytest


@pytest.mark.asyncio
async def test_list_candidates_filters_and_paginates():
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateRevision,
        CandidateStatus,
        User,
        Workspace,
    )
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
        _, items = await list_candidates(db, ws.id, scopes={"active", "pending_review", "rejected"},
                                         page=1, page_size=10)
        names = {i["name"] for i in items}
        assert "张三" in names and "王五" in names
        assert "李四" not in names

        # admin 可见 hired
        _, items2 = await list_candidates(db, ws.id, scopes={"active", "pending_review", "rejected", "hired"},
                                          page=1, page_size=10)
        assert any(i["name"] == "李四" for i in items2)

        # 技能筛选
        _, items3 = await list_candidates(db, ws.id, scopes={"active", "pending_review", "rejected", "hired"},
                                          skills=["Java"], page=1, page_size=10)
        assert len(items3) >= 2

        # 学历 range_degree 筛选（本科及以上）
        _, items4 = await list_candidates(db, ws.id, scopes={"active", "pending_review", "rejected", "hired"},
                                          degree_at_least="本科", page=1, page_size=10)
        assert len(items4) >= 1

        # 年限筛选
        _, items5 = await list_candidates(db, ws.id, scopes={"active", "pending_review", "rejected", "hired"},
                                          years_min=4, page=1, page_size=10)
        assert len(items5) >= 1

        # 分页
        total6, items6 = await list_candidates(db, ws.id, scopes={"active", "pending_review", "rejected", "hired"},
                                               page=1, page_size=1)
        assert total6 == 3 and len(items6) == 1

@pytest.mark.asyncio
async def test_list_candidates_filters_by_referrer():
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateStatus,
        ParseRun,
        ResumeFile,
        User,
        Workspace,
    )
    from app.services.candidate_list import list_candidates

    async with SessionLocal() as db:
        from app.models import CandidateRevision
        owner = User(email="ref-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="ref-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        c1 = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                       structured_data={}, search_text="")
        c2 = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="李四",
                       structured_data={}, search_text="")
        db.add_all([c1, c2])
        await db.flush()
        for cand, run_id, ref in ((c1, "ref-r1", "王经理"), (c2, "ref-r2", None)):
            rev = CandidateRevision(candidate_id=cand.id, run_id=run_id, revision_id=f"{run_id}:rev1",
                                    candidate_json={"name": cand.name}, evidence={})
            db.add(rev)
            await db.flush()
            cand.latest_revision_id = rev.id
            run = ParseRun(run_id=run_id, workspace_id=ws.id, upload_id="u", source_channel="referral",
                           referrer=ref, format="pdf", file_hash=run_id, file_path="p", file_size=1,
                           parser_version="v1")
            db.add(run)
            await db.flush()
            db.add(ResumeFile(run_id=run_id, candidate_id=cand.id, file_hash=run_id, storage_key="k",
                              format="pdf", file_size=1, content_type="application/pdf"))
        await db.commit()

        total, items = await list_candidates(db, ws.id, scopes={"active"},
                                             referrer="王经理", page=1, page_size=10)
        assert total == 1 and items[0]["name"] == "张三"


@pytest.mark.asyncio
async def test_list_candidates_filters_by_interview_result_without_duplicates():
    from app.core.database import SessionLocal
    from app.models import Assignment, AssignmentStatus, Candidate, CandidateRevision, CandidateStatus, Job, User, Workspace
    from app.services.candidate_list import list_candidates

    async with SessionLocal() as db:
        owner = User(email="interview-filter-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="interview-filter-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        candidate = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="通过者",
                              structured_data={}, search_text="")
        other = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="未履行者",
                          structured_data={}, search_text="")
        job1 = Job(workspace_id=ws.id, name="后端", description="", headcount=2)
        job2 = Job(workspace_id=ws.id, name="前端", description="", headcount=2)
        db.add_all([candidate, other, job1, job2])
        await db.flush()
        for index, cand in enumerate((candidate, other), start=1):
            revision = CandidateRevision(candidate_id=cand.id, run_id=f"interview-filter-{index}",
                                         revision_id=f"interview-filter-{index}:rev1",
                                         candidate_json={"name": cand.name}, evidence={})
            db.add(revision)
            await db.flush()
            cand.latest_revision_id = revision.id
        db.add_all([
            Assignment(workspace_id=ws.id, candidate_id=candidate.id, job_id=job1.id,
                       status=AssignmentStatus.interviewing, interview_result="passed"),
            Assignment(workspace_id=ws.id, candidate_id=candidate.id, job_id=job2.id,
                       status=AssignmentStatus.interviewing, interview_result="passed"),
            Assignment(workspace_id=ws.id, candidate_id=other.id, job_id=job1.id,
                       status=AssignmentStatus.interviewing, interview_result="no_show"),
        ])
        await db.commit()
        total, items = await list_candidates(db, ws.id, scopes={"active"}, interview_result="passed")
        assert total == 1 and [item["name"] for item in items] == ["通过者"]
