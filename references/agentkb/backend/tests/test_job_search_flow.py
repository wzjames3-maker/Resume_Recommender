import pytest

from app.models import (
    Candidate,
    CandidateEmbedding,
    CandidateRevision,
    CandidateStatus,
    Job,
    JobRequirementRevision,
    User,
    Workspace,
)
from app.services.search.flow import run_search_flow


class FakeLLM:
    def __init__(self, intent="job_search", job_id=None, job_title="前端", conditions=None,
                 requested_count=None):
        self._out = {"intent": intent, "job_id": job_id, "job_title": job_title,
                     "requested_count": requested_count, "pool_scope": "active",
                     "conditions": conditions or [], "reason": ""}

    async def chat_json(self, system, user, schema):
        return self._out


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1] * 1024 for _ in texts]


class FakeRerank:
    async def rerank(self, query, documents):
        return list(range(len(documents)))


async def _seed(db, ws_id):
    cand = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                     structured_data={"skills": ["Vue"], "years_experience": 6}, search_text="Vue 前端")
    db.add(cand)
    await db.flush()
    rev = CandidateRevision(candidate_id=cand.id, run_id="jf-r", revision_id=f"jf-r:{id(cand)}:rev1",
                            candidate_json={"skills": ["Vue"]}, evidence={},
                            profile_json={"values": {"level": "Mid"}, "evidence": {}})
    db.add(rev)
    await db.flush()
    cand.latest_revision_id = rev.id
    db.add(CandidateEmbedding(candidate_id=cand.id, revision_id=rev.revision_id, segment="work",
                              text="Vue 前端", embedding=[0.1] * 1024))


def _patch(monkeypatch, llm):
    async def fake_get_llm(db, ws):
        return llm

    async def fake_get_embedder(db, ws):
        return FakeEmbedder()

    async def fake_get_rerank(db, ws):
        return FakeRerank()

    monkeypatch.setattr("app.services.search.flow._get_llm", fake_get_llm)
    monkeypatch.setattr("app.services.search.flow._get_embedder", fake_get_embedder)
    monkeypatch.setattr("app.services.search.flow._get_rerank", fake_get_rerank)


@pytest.mark.asyncio
async def test_job_search_ambiguous_returns_job_candidates(monkeypatch):
    from app.core.database import SessionLocal

    _patch(monkeypatch, FakeLLM(job_title="前端"))
    async with SessionLocal() as db:
        owner = User(email="jf-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="jf-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        j1 = Job(workspace_id=ws.id, name="前端开发工程师", description="", headcount=1)
        j2 = Job(workspace_id=ws.id, name="前端开发工程师", description="", headcount=1)
        db.add_all([j1, j2])
        await db.commit()
        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member",
                                        actor_id=owner.id, utterance="我要前端岗位的简历", prior_context=None)
        assert outcome.intent == "job_search"
        assert outcome.cards == []
        assert outcome.job_candidates and len(outcome.job_candidates) == 2


@pytest.mark.asyncio
async def test_job_search_executes_with_job_ast(monkeypatch):
    from app.core.database import SessionLocal

    _patch(monkeypatch, FakeLLM(job_title="前端", requested_count=20))
    async with SessionLocal() as db:
        owner = User(email="jf2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="jf2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        job = Job(workspace_id=ws.id, name="前端开发工程师", description="5 年经验，精通 Vue", headcount=1)
        db.add(job)
        await db.flush()
        rev = JobRequirementRevision(job_id=job.id, revision=1, description=job.description,
                                     parsed_ast=[{"field": "skills", "op": "contains", "value": ["Vue"],
                                                  "logic": "AND", "missing_policy": "exclude"}],
                                     schema_version="search/v1", prompt_version="job-req-prompt/v1",
                                     evidence={"skills": {"locator": "精通 Vue"}})
        db.add(rev)
        await db.flush()
        job.latest_revision_id = rev.id
        await _seed(db, ws.id)
        await db.commit()
        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member",
                                        actor_id=owner.id, utterance="我需要 20 份匹配前端岗位的简历",
                                        prior_context=None)
        assert outcome.intent == "job_search"
        assert outcome.cards and outcome.cards[0]["name"] == "张三"
        assert "前端开发工程师" in outcome.summary
        assert outcome.context["job_id"] == job.id


@pytest.mark.asyncio
async def test_job_search_closed_or_missing(monkeypatch):
    from app.core.database import SessionLocal
    from app.models import JobStatus

    _patch(monkeypatch, FakeLLM(job_title="不存在"))
    async with SessionLocal() as db:
        owner = User(email="jf3-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="jf3-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await db.commit()
        out = await run_search_flow(db, workspace_id=ws.id, actor_role="member",
                                    actor_id=owner.id, utterance="找测试岗位的人", prior_context=None)
        assert out.intent == "job_search" and out.cards == []
        assert "未找到" in out.summary

    _patch(monkeypatch, FakeLLM(job_title="后端"))
    async with SessionLocal() as db:
        owner = User(email="jf4-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="jf4-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        job = Job(workspace_id=ws.id, name="后端开发", description="", headcount=1, status=JobStatus.closed)
        db.add(job)
        await db.commit()
        out = await run_search_flow(db, workspace_id=ws.id, actor_role="member",
                                    actor_id=owner.id, utterance="给我后端岗位的人", prior_context=None)
        assert "已关闭" in out.summary

@pytest.mark.asyncio
async def test_job_search_switch_job_in_next_turn_not_stuck(monkeypatch):
    """C-1 回归：第二轮带新 job_title 时不得回退上一轮 job_id。"""
    from app.core.database import SessionLocal

    class SwitchingLLM(FakeLLM):
        def __init__(self, outputs):
            self._outputs = list(outputs)
            super().__init__()

        async def chat_json(self, system, user, schema):
            return self._outputs.pop(0)

    from app.services.search.flow import run_search_flow
    async with SessionLocal() as db:
        owner = User(email="jf5-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="jf5-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        jfront = Job(workspace_id=ws.id, name="前端开发工程师", description="精通 Vue", headcount=1)
        jback = Job(workspace_id=ws.id, name="后端开发工程师", description="精通 Java", headcount=1)
        db.add_all([jfront, jback])
        await db.flush()
        for job in (jfront, jback):
            jr = JobRequirementRevision(job_id=job.id, revision=1, description=job.description,
                                        parsed_ast=[], schema_version="search/v1",
                                        prompt_version="job-req-prompt/v1", evidence={})
            db.add(jr)
            await db.flush()
            job.latest_revision_id = jr.id
        await db.commit()

        llm = SwitchingLLM([
            {"intent": "job_search", "job_id": None, "job_title": "前端",
             "requested_count": None, "pool_scope": "active", "conditions": [], "reason": ""},
            {"intent": "job_search", "job_id": None, "job_title": "后端",
             "requested_count": None, "pool_scope": "active", "conditions": [], "reason": ""},
        ])
        _patch(monkeypatch, llm)

        out1 = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                     utterance="我要前端岗位的简历", prior_context=None)
        assert out1.intent == "job_search" and out1.context["job_id"] == jfront.id
        out2 = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                     utterance="换个岗位，看后端的", prior_context=out1.context)
        assert out2.intent == "job_search"
        assert out2.context["job_id"] == jback.id
        assert "后端开发工程师" in out2.summary


@pytest.mark.asyncio
async def test_search_history_predicate_filters_offer_rejected(monkeypatch):
    from app.core.database import SessionLocal
    from app.models import Assignment, AssignmentStatus

    class HistoryLLM(FakeLLM):
        def __init__(self):
            super().__init__(job_title="前端", requested_count=20)
            self._has_history = True

        async def chat_json(self, system, user, schema):
            out = dict(self._out)
            out["assignment_history"] = [{"event": "offer_rejected"}] if self._has_history else []
            return out

    _patch(monkeypatch, HistoryLLM())
    async with SessionLocal() as db:
        owner = User(email="jf6-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="jf6-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id)
        for name in ("李四", "王五"):
            cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name=name,
                             structured_data={"skills": ["Vue"], "years_experience": 4},
                             search_text="Vue 前端")
            db.add(cand)
            await db.flush()
            rev = CandidateRevision(candidate_id=cand.id, run_id=f"jf6-r:{id(cand)}",
                                    revision_id=f"jf6-r:{id(cand)}:rev1",
                                    candidate_json={"skills": ["Vue"]}, evidence={},
                                    profile_json={"values": {"level": "Mid"}, "evidence": {}})
            db.add(rev)
            await db.flush()
            cand.latest_revision_id = rev.id
            db.add(CandidateEmbedding(candidate_id=cand.id, revision_id=rev.revision_id, segment="work",
                                      text="Vue 前端", embedding=[0.1] * 1024))
        job = Job(workspace_id=ws.id, name="前端开发工程师", description="精通 Vue", headcount=1)
        db.add(job)
        await db.flush()
        jr = JobRequirementRevision(job_id=job.id, revision=1, description=job.description,
                                    parsed_ast=[], schema_version="search/v1",
                                    prompt_version="job-req-prompt/v1", evidence={})
        db.add(jr)
        await db.flush()
        job.latest_revision_id = jr.id
        candidates = (await db.execute(
            __import__("sqlalchemy").select(Candidate).where(Candidate.workspace_id == ws.id)
            .order_by(Candidate.id))).scalars().all()
        db.add(Assignment(workspace_id=ws.id, candidate_id=candidates[1].id, job_id=job.id,
                          status=AssignmentStatus.offer_rejected, created_by=owner.id))
        await db.commit()

        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                        utterance="找拒绝过 offer 的前端候选人", prior_context=None)
        assert outcome.cards
        assert {c["name"] for c in outcome.cards} == {"李四"}
