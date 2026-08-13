import pytest


class FakeLLM:
    def __init__(self, parsed):
        self._parsed = parsed

    async def chat_json(self, system, user, schema):
        return self._parsed


_PARSED = {
    "conditions": [
        {"field": "skills", "op": "contains", "value": ["Vue"], "logic": "AND", "missing_policy": "exclude"},
        {"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"},
    ],
    "evidence": {
        "skills": {"locator": "精通 Vue", "reason": ""},
        "years_experience": {"locator": "5 年", "reason": ""},
    },
    "reason": "",
}


@pytest.mark.asyncio
async def test_create_job_parses_and_creates_revision():
    from app.core.database import SessionLocal
    from app.models import JobRequirementRevision, User, Workspace
    from app.services.job_service import create_job

    async with SessionLocal() as db:
        owner = User(email="js-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="js-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()

        job, ast = await create_job(db, workspace_id=ws.id, name="前端开发工程师",
                                    description="5 年经验，精通 Vue", headcount=2,
                                    city="杭州", salary_range="25-40k", actor_id=owner.id,
                                    llm=FakeLLM(_PARSED))
        await db.commit()
        assert ast[0]["field"] == "skills"
        rev = await db.get(JobRequirementRevision, job.latest_revision_id)
        assert rev.revision == 1
        assert rev.description == "5 年经验，精通 Vue"
        assert rev.schema_version == "search/v1"


@pytest.mark.asyncio
async def test_update_job_description_creates_new_revision_and_conflict():
    from app.core.database import SessionLocal
    from app.models import JobRequirementRevision, User, Workspace
    from app.services.job_service import create_job, update_job

    async with SessionLocal() as db:
        owner = User(email="js2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="js2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        job, _ = await create_job(db, workspace_id=ws.id, name="后端", description="3 年 Java",
                                  headcount=1, city=None, salary_range=None, actor_id=owner.id,
                                  llm=FakeLLM(_PARSED))
        await db.commit()
        assert job.latest_revision_id is not None

        new_parsed = {
            "conditions": [
                {"field": "skills", "op": "contains", "value": ["Go"], "logic": "AND", "missing_policy": "exclude"},
            ],
            "evidence": {"skills": {"locator": "精通 Go", "reason": ""}},
            "reason": "",
        }
        job2, changed = await update_job(db, job=job, base_revision_id=job.latest_revision_id,
                                         name=None, description="3 年 Go 经验", headcount=None,
                                         city=None, salary_range=None, status=None, actor_id=owner.id,
                                         llm=FakeLLM(new_parsed))
        await db.commit()
        assert changed is True
        rev = await db.get(JobRequirementRevision, job2.latest_revision_id)
        assert rev.revision == 2
        assert rev.parsed_ast[0]["value"] == ["Go"]

        # 乐观锁冲突
        from app.services.job_service import JobConflictError
        with pytest.raises(JobConflictError):
            await update_job(db, job=job2, base_revision_id=999, name=None, description="x",
                             headcount=None, city=None, salary_range=None, status=None,
                             actor_id=owner.id, llm=FakeLLM(new_parsed))


@pytest.mark.asyncio
async def test_resolve_job_direct_and_ambiguous_and_not_found():
    from app.core.database import SessionLocal
    from app.models import Job, User, Workspace
    from app.services.job_service import resolve_job

    async with SessionLocal() as db:
        owner = User(email="js3-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="js3-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        j1 = Job(workspace_id=ws.id, name="前端开发工程师", description="", headcount=1)
        j2 = Job(workspace_id=ws.id, name="前端开发工程师", description="", headcount=1)
        j3 = Job(workspace_id=ws.id, name="后端开发", description="", headcount=1)
        db.add_all([j1, j2, j3])
        await db.commit()

        # 唯一名称直接命中
        job, _, ambiguous = await resolve_job(db, ws.id, job_id=None, job_title="后端")
        assert job.id == j3.id and ambiguous is False
        # 同名多选 → 候选列表
        job, candidates, ambiguous = await resolve_job(db, ws.id, job_id=None, job_title="前端")
        assert job is None and ambiguous is True and len(candidates) == 2
        # job_id 直接
        job, _, ambiguous = await resolve_job(db, ws.id, job_id=j1.id, job_title=None)
        assert job.id == j1.id and ambiguous is False
        # 找不到
        job, candidates, ambiguous = await resolve_job(db, ws.id, job_id=None, job_title="不存在岗位")
        assert job is None and candidates == [] and ambiguous is False


@pytest.mark.asyncio
async def test_count_matching_candidates_reuses_filter():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, User, Workspace
    from app.services.job_service import count_matching_candidates

    async with SessionLocal() as db:
        owner = User(email="js4-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="js4-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        c1 = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                       structured_data={"skills": ["Vue"], "years_experience": 6}, search_text="Vue")
        c2 = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="李四",
                       structured_data={"skills": ["Java"], "years_experience": 2}, search_text="Java")
        db.add_all([c1, c2])
        await db.commit()

        n = await count_matching_candidates(db, ws.id, _PARSED["conditions"], scopes={"active", "rejected"})
        assert n == 1
        n0 = await count_matching_candidates(db, ws.id, [], scopes={"active"})
        assert n0 == 0