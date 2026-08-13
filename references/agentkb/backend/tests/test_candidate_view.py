import pytest


@pytest.mark.asyncio
async def test_candidate_event_roundtrip():
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateEvent,
        CandidateEventType,
        CandidateStatus,
        User,
        Workspace,
    )

    async with SessionLocal() as db:
        owner = User(email="evt-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="evt-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={}, search_text="")
        db.add(cand)
        await db.flush()
        evt = CandidateEvent(candidate_id=cand.id, event_type=CandidateEventType.created,
                             title="候选人创建", actor_id=owner.id, detail={"source": "parse"})
        db.add(evt)
        await db.commit()
        # 新会话读回：String 列返回纯字符串值（非枚举对象），验证列往返
        from sqlalchemy import select
        got = (await db.execute(select(CandidateEvent).where(CandidateEvent.id == evt.id))).scalar_one()
        assert got.event_type == CandidateEventType.created.value
        assert got.detail["source"] == "parse"

def test_resolve_and_set_path():
    from app.services.candidate_view import get_path, set_path
    obj = {"name": "张三", "work": [{"company": "A", "title": "工程师"}]}
    out = set_path(obj, "work[0].title", "高级工程师")
    assert out["work"][0]["title"] == "高级工程师"
    out2 = set_path(obj, "city", "杭州")
    assert out2["city"] == "杭州"
    assert get_path(out, "work[0].title") == "高级工程师"
    assert get_path(out, "city") is None


def test_apply_overrides_override_and_clear():
    from app.services.candidate_view import apply_overrides
    base = {"name": "张三", "city": "杭州", "work": [{"company": "A", "title": "工程师"}]}
    overrides = [
        {"field_path": "city", "action": "override", "after_value": "上海"},
        {"field_path": "work[0].title", "action": "override", "after_value": "高级工程师"},
        {"field_path": "name", "action": "clear", "after_value": None},
    ]
    merged = apply_overrides(base, overrides)
    assert merged["city"] == "上海"
    assert merged["work"][0]["title"] == "高级工程师"
    assert merged["name"] is None


@pytest.mark.asyncio
async def test_effective_view_applies_overrides():
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateOverride,
        CandidateRevision,
        CandidateStatus,
        User,
        Workspace,
    )
    from app.services.candidate_view import build_effective_view

    async with SessionLocal() as db:
        owner = User(email="view-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="view-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        cand = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                         structured_data={"city": "杭州"}, search_text="")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="view-r", revision_id="view-r:rev1",
                                candidate_json={"name": "张三", "city": "杭州", "skills": ["Java"]},
                                evidence={}, profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        db.add(CandidateOverride(candidate_id=cand.id, revision_id="view-r:rev1", field_path="city",
                                 before_value="杭州", after_value="上海", action="override", actor_id=owner.id))
        await db.commit()
        view = await build_effective_view(db, cand.id)
        assert view["fields"]["city"] == "上海"
        assert view["fields"]["skills"] == ["Java"]
        assert view["profile"]["level"] == "Mid"


def test_set_path_writes_back_intermediate_containers():
    # I-1 回归：路径穿越标量中间节点时，新容器必须写回父节点
    from app.services.candidate_view import set_path
    obj = {"name": "张三"}
    out = set_path(obj, "name.sub", "v")
    assert out["name"]["sub"] == "v"
    obj2 = {"work": ["A"]}
    out2 = set_path(obj2, "work[0].title", "v")
    assert out2["work"][0]["title"] == "v"
