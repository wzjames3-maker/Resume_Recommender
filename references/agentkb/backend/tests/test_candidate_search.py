import pytest

from app.services.candidate_search import ALLOWED_SCOPES_BY_ROLE, search_candidates
from app.services.search.cards import build_candidate_cards
from app.services.search.schema import validate_conditions


@pytest.mark.asyncio
async def test_allowed_scopes_by_role():
    assert ALLOWED_SCOPES_BY_ROLE["member"] == {"active", "rejected"}
    assert "hired" in ALLOWED_SCOPES_BY_ROLE["admin"]
    assert "hired" in ALLOWED_SCOPES_BY_ROLE["owner"]


async def _seed_candidate(db, *, email: str, ws_name: str, status=None, structured=None,
                          profile=None, search_text: str = "Java 支付", embedding: bool = False):
    from app.models import (
        Candidate,
        CandidateRevision,
        CandidateStatus,
        User,
        Workspace,
    )

    owner = User(email=email, hashed_password="x", nickname="o")
    db.add(owner)
    await db.flush()
    ws = Workspace(name=ws_name, owner_id=owner.id)
    db.add(ws)
    await db.flush()
    cand = Candidate(workspace_id=ws.id, status=status or CandidateStatus.active, name="张三",
                     structured_data=structured, search_text=search_text)
    db.add(cand)
    await db.flush()
    rev = CandidateRevision(candidate_id=cand.id, run_id=ws_name, revision_id=f"{ws_name}:rev1",
                            candidate_json={"skills": ["Java"]}, evidence={},
                            profile_json={"values": profile or {}, "evidence": {}})
    db.add(rev)
    await db.flush()
    cand.latest_revision_id = rev.id
    if embedding:
        from app.models import CandidateEmbedding

        db.add(CandidateEmbedding(candidate_id=cand.id, revision_id=f"{ws_name}:rev1", segment="work",
                                  text="支付系统", embedding=[0.1] * 1024))
    return ws.id, cand.id


@pytest.mark.asyncio
async def test_search_candidates_filters_by_scopes_and_conditions():
    from app.core.database import SessionLocal
    from app.models import CandidateEmbedding

    async with SessionLocal() as db:
        ws_id, cand_id = await _seed_candidate(
            db, email="cs-owner@example.com", ws_name="cs-ws",
            structured={"skills": ["Java"], "years_experience": 6, "city": "杭州",
                        "highest_degree": "本科", "expected_city": "杭州"})
        db.add(CandidateEmbedding(candidate_id=cand_id, revision_id="cs-ws:rev1", segment="work",
                                  text="支付系统", embedding=[0.1] * 1024))
        await db.commit()
        conds = [
            {"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"},
            {"fields": ["city", "expected_city"], "op": "any_match", "value": "杭州", "logic": "AND", "missing_policy": "exclude"},
            {"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"},
        ]
        validate_conditions(conds)
        hits = await search_candidates(db, ws_id, [0.1] * 1024, "Java 支付", conds,
                                       scopes={"active"}, top_k=10)
        assert [h.candidate_id for h in hits] == [cand_id]
        cards = await build_candidate_cards(db, [h.candidate_id for h in hits], conds)
        assert "skills" in cards[0]["matched_conditions"]


@pytest.mark.asyncio
async def test_profile_condition_filter_matches_candidate():
    # Critical-1 回归：画像条件必须经 latest_revision.profile_json 过滤（结构化数据不含画像）
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        ws_id, cand_id = await _seed_candidate(
            db, email="cs3-owner@example.com", ws_name="cs3-ws",
            structured={"skills": ["Java"], "highest_degree": "硕士"},
            profile={"level": "Senior", "domain": "金融科技"}, search_text="高级工程师")
        await db.commit()
        conds = [{"field": "level", "op": "eq", "value": "Senior", "logic": "AND", "missing_policy": "exclude"}]
        hits = await search_candidates(db, ws_id, [0.1] * 1024, "高级工程师", conds, scopes={"active"}, top_k=10)
        assert [h.candidate_id for h in hits] == [cand_id]
        cards = await build_candidate_cards(db, [h.candidate_id for h in hits], conds)
        assert "level" in cards[0]["matched_conditions"]
        assert cards[0]["profile"]["level"] == "Senior"


@pytest.mark.asyncio
async def test_profile_condition_filter_does_not_leak_wrong_level():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        ws_id, _ = await _seed_candidate(
            db, email="cs4-owner@example.com", ws_name="cs4-ws",
            structured={"skills": ["Java"]}, profile={"level": "Mid"}, search_text="高级工程师")
        await db.commit()
        conds = [{"field": "level", "op": "eq", "value": "Senior", "logic": "AND", "missing_policy": "exclude"}]
        hits = await search_candidates(db, ws_id, [0.1] * 1024, "高级工程师", conds, scopes={"active"}, top_k=10)
        assert hits == []


@pytest.mark.asyncio
async def test_range_degree_matches_ordinal_ge():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        ws_id, cand_id = await _seed_candidate(
            db, email="cs5-owner@example.com", ws_name="cs5-ws",
            structured={"skills": ["Java"], "highest_degree": "硕士"}, search_text="Java")
        await db.commit()
        conds = [{"field": "highest_degree", "op": "range_degree", "value": "本科", "logic": "AND", "missing_policy": "exclude"}]
        hits = await search_candidates(db, ws_id, [0.1] * 1024, "Java", conds, scopes={"active"}, top_k=10)
        assert [h.candidate_id for h in hits] == [cand_id]
        cards = await build_candidate_cards(db, [h.candidate_id for h in hits], conds)
        assert "highest_degree" in cards[0]["matched_conditions"]


@pytest.mark.asyncio
async def test_search_candidates_excludes_hired_for_member():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="cs2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cs2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        db.add(Candidate(workspace_id=ws.id, status=CandidateStatus.hired, name="李四",
                         structured_data={"skills": ["Java"]}, search_text="Java"))
        await db.commit()
        hits = await search_candidates(db, ws.id, [0.1] * 1024, "Java", [], scopes={"active"}, top_k=10)
        assert hits == []


@pytest.mark.asyncio
async def test_build_candidate_cards_includes_hit_conditions_no_score():
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        _, cand_id = await _seed_candidate(
            db, email="card-owner@example.com", ws_name="card-ws",
            structured={"city": "杭州", "highest_degree": "本科", "years_experience": 6,
                        "expected_position": "Java 后端", "skills": ["Java"]},
            profile={"level": "Mid", "domain": "金融科技"})
        await db.commit()
        cards = await build_candidate_cards(db, [cand_id], [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}])
        assert cards[0]["candidate_id"] == cand_id
        assert cards[0]["name"] == "张三"
        assert "skills" in cards[0]["matched_conditions"]
        assert "score" not in cards[0]