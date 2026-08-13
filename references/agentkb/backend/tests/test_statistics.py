import uuid

import pytest

from app.models import (
    Candidate,
    CandidateRevision,
    CandidateStatus,
    User,
    Workspace,
)
from app.services.search.statistics import compute_statistics


async def _seed(db, ws_id, *, name, city=None, degree=None, years=None, level=None, status=CandidateStatus.active):
    is_java = name.startswith("J")
    rid = f"st-{uuid.uuid4().hex}"
    cand = Candidate(workspace_id=ws_id, status=status, name=name,
                     structured_data={"skills": ["Java"] if is_java else ["Vue"],
                                      "city": city, "highest_degree": degree, "years_experience": years},
                     search_text=f"{name} Java" if is_java else name)
    db.add(cand)
    await db.flush()
    rev = CandidateRevision(candidate_id=cand.id, run_id=rid, revision_id=f"{rid}:r1",
                            candidate_json={"skills": ["Java"]}, evidence={},
                            profile_json={"values": {"level": level}, "evidence": {}})
    db.add(rev)
    await db.flush()
    cand.latest_revision_id = rev.id


@pytest.mark.asyncio
async def test_compute_statistics_count_and_city_distribution():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        owner = User(email="st-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="st-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州", degree="本科", years=5)
        await _seed(db, ws.id, name="Java2", city="杭州", degree="硕士", years=3)
        await _seed(db, ws.id, name="Java3", city="上海", degree="本科", years=8)
        await _seed(db, ws.id, name="Vue4", city="北京", degree="本科", years=2)
        await db.commit()

        conds = [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}]
        stats = await compute_statistics(db, workspace_id=ws.id, conditions=conds,
                                         scopes={"active"}, group_by="city")
        assert stats["count"] == 3
        assert stats["dimension"] == "city"
        by_city = {g["key"]: g["count"] for g in stats["distribution"]}
        assert by_city == {"杭州": 2, "上海": 1}


@pytest.mark.asyncio
async def test_compute_statistics_count_only_and_pool_filter():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        owner = User(email="st2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="st2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州")
        await db.commit()

        stats = await compute_statistics(db, workspace_id=ws.id, conditions=[], scopes={"active"}, group_by=None)
        assert stats["count"] == 1
        assert stats["dimension"] is None
        assert stats["distribution"] == []

        stats_rej = await compute_statistics(db, workspace_id=ws.id, conditions=[], scopes={"rejected"}, group_by=None)
        assert stats_rej["count"] == 0


@pytest.mark.asyncio
async def test_compute_statistics_profile_dimension_joins_revision():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        owner = User(email="st3-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="st3-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州", level="Mid")
        await _seed(db, ws.id, name="Java2", city="杭州", level="Senior")
        await db.commit()

        stats = await compute_statistics(db, workspace_id=ws.id, conditions=[], scopes={"active"}, group_by="level")
        by_level = {g["key"]: g["count"] for g in stats["distribution"]}
        assert by_level == {"Mid": 1, "Senior": 1}


@pytest.mark.asyncio
async def test_compute_statistics_rejects_unknown_dimension():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        with pytest.raises(ValueError, match="非法统计维度"):
            await compute_statistics(db, workspace_id=1, conditions=[], scopes={"active"}, group_by="salary")


from app.core.database import SessionLocal
from app.services.search.flow import run_search_flow


class FakeLLM:
    def __init__(self, intent="statistics", stat_group_by=None, conditions=None, pool_scope="active",
                 assignment_history=None):
        self._out = {"intent": intent, "requested_count": None, "pool_scope": pool_scope,
                     "conditions": conditions or [], "stat_group_by": stat_group_by,
                     "job_id": None, "job_title": None, "reason": "",
                     "assignment_history": assignment_history or []}

    async def chat_json(self, system, user, schema):
        return self._out


def _patch(monkeypatch, llm):
    async def fake_get_llm(db, ws):
        return llm

    async def fake_get_embedder(db, ws):
        raise AssertionError("统计查询不应调用 embedder")

    async def fake_get_rerank(db, ws):
        raise AssertionError("统计查询不应调用 rerank")

    monkeypatch.setattr("app.services.search.flow._get_llm", fake_get_llm)
    monkeypatch.setattr("app.services.search.flow._get_embedder", fake_get_embedder)
    monkeypatch.setattr("app.services.search.flow._get_rerank", fake_get_rerank)


@pytest.mark.asyncio
async def test_statistics_flow_returns_card_with_distribution(monkeypatch):
    _patch(monkeypatch, FakeLLM(stat_group_by="city"))
    async with SessionLocal() as db:
        owner = User(email="stf-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="stf-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州")
        await _seed(db, ws.id, name="Java2", city="上海")
        await db.commit()
        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                        utterance="人才库里有多少 Java 候选人？城市分布？", prior_context=None)
        assert outcome.intent == "statistics"
        assert outcome.statistics is not None
        assert outcome.statistics["count"] == 2
        assert outcome.statistics["dimension"] == "city"
        assert {g["key"]: g["count"] for g in outcome.statistics["distribution"]} == {"杭州": 1, "上海": 1}
        assert "城市分布" in outcome.summary


@pytest.mark.asyncio
async def test_statistics_flow_count_only(monkeypatch):
    _patch(monkeypatch, FakeLLM(stat_group_by=None))
    async with SessionLocal() as db:
        owner = User(email="stf2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="stf2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州")
        await db.commit()
        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                        utterance="有多少 Java 候选人？", prior_context=None)
        assert outcome.intent == "statistics"
        assert outcome.statistics["count"] == 1
        assert outcome.statistics["dimension"] is None


@pytest.mark.asyncio
async def test_statistics_flow_pool_denied(monkeypatch):
    _patch(monkeypatch, FakeLLM(stat_group_by=None, pool_scope="hired"))
    async with SessionLocal() as db:
        owner = User(email="stf3-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="stf3-ws", owner_id=owner.id)
        db.add(ws)
        await db.commit()
        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                        utterance="入职员工库有多少人？", prior_context=None)
        assert outcome.intent == "statistics"
        assert outcome.statistics is None
        assert "无权限" in outcome.summary


@pytest.mark.asyncio
async def test_statistics_flow_audit_payload_desensitized(monkeypatch):
    from sqlalchemy import select

    from app.models import AuditEvent

    _patch(monkeypatch, FakeLLM(stat_group_by="city"))
    async with SessionLocal() as db:
        owner = User(email="stf4-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="stf4-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州")
        await db.commit()
        await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                              utterance="有多少 Java 候选人？城市分布？", prior_context=None)
        evt = (await db.execute(
            select(AuditEvent).where(AuditEvent.action == "search.statistics.executed",
                                     AuditEvent.workspace_id == ws.id))).scalar_one()
        assert evt.payload == {"count": 1, "dimension": "city"}
        assert "Java" not in str(evt.payload)


@pytest.mark.asyncio
async def test_statistics_history_predicate_filters_visible_candidates(monkeypatch):
    from app.models import Assignment, AssignmentStatus, Job

    _patch(monkeypatch, FakeLLM(assignment_history=[{"event": "offer_rejected"}]))
    async with SessionLocal() as db:
        owner = User(email="sth-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="sth-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        await _seed(db, ws.id, name="Java1", city="杭州")
        await _seed(db, ws.id, name="Java2", city="上海")
        candidates = (await db.execute(__import__("sqlalchemy").select(Candidate).where(
            Candidate.workspace_id == ws.id).order_by(Candidate.id))).scalars().all()
        job = Job(workspace_id=ws.id, name="后端", description="", headcount=2)
        db.add(job)
        await db.flush()
        db.add(Assignment(workspace_id=ws.id, candidate_id=candidates[0].id, job_id=job.id,
                          status=AssignmentStatus.offer_rejected, created_by=owner.id))
        await db.commit()

        outcome = await run_search_flow(db, workspace_id=ws.id, actor_role="member", actor_id=owner.id,
                                         utterance="有多少曾拒绝 offer 的人？", prior_context=None)
        assert outcome.statistics["count"] == 1
