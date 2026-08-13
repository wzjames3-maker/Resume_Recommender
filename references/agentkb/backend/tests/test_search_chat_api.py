import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _seed_candidate(ws_id: int):
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateEmbedding,
        CandidateRevision,
        CandidateStatus,
    )

    async with SessionLocal() as db:
        cand = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                         structured_data={"skills": ["Java"], "years_experience": 6, "city": "杭州",
                                          "highest_degree": "本科", "expected_city": "杭州"},
                         search_text="Java 支付")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="scc-r", revision_id="scc-r:rev1",
                                candidate_json={"skills": ["Java"]}, evidence={},
                                profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        db.add(CandidateEmbedding(candidate_id=cand.id, revision_id="scc-r:rev1", segment="work",
                                  text="支付系统", embedding=[0.1] * 1024))
        await db.commit()


@pytest.mark.asyncio
async def test_search_chat_returns_candidate_cards(monkeypatch):
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"intent": "search", "requested_count": None, "pool_scope": "active",
                    "conditions": [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}],
                    "reason": "找 Java"}

    class FakeEmbedder:
        async def embed(self, texts):
            return [[0.1] * 1024 for _ in texts]

    class FakeRerank:
        async def rerank(self, query, documents):
            return list(range(len(documents)))

    async def fake_get_llm(db, ws):
        return FakeLLM()

    async def fake_get_embedder(db, ws):
        return FakeEmbedder()

    async def fake_get_rerank(db, ws):
        return FakeRerank()

    monkeypatch.setattr("app.services.search.flow._get_llm", fake_get_llm)
    monkeypatch.setattr("app.services.search.flow._get_embedder", fake_get_embedder)
    monkeypatch.setattr("app.services.search.flow._get_rerank", fake_get_rerank)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "sc@b.com", "password": "secret123", "nickname": "S"})
        token = (await c.post("/api/v1/auth/login", json={"email": "sc@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "SC-WS"}, headers=h)).json()["id"]
        await _seed_candidate(ws_id)
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "找 Java 后端", "stream": False}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "search"
        assert body["cards"] and body["cards"][0]["name"] == "张三"
        assert "score" not in body["cards"][0]
        assert body["cards"][0]["profile"]["level"] == "Mid"


@pytest.mark.asyncio
async def test_search_chat_rejects_write_request_without_side_effect(monkeypatch):
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"intent": "write_request", "requested_count": None, "pool_scope": None,
                    "conditions": [], "reason": "批量指派"}

    async def fake_get_llm(db, ws):
        return FakeLLM()

    monkeypatch.setattr("app.services.search.flow._get_llm", fake_get_llm)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "sc2@b.com", "password": "secret123", "nickname": "S2"})
        token = (await c.post("/api/v1/auth/login", json={"email": "sc2@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "SC2-WS"}, headers=h)).json()["id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "把这些人批量指派到岗位", "stream": False}, headers=h)
        assert r.status_code == 200
        assert r.json()["intent"] == "write_request"
        assert r.json()["cards"] == []
        assert "工作台" in r.json()["summary"]

@pytest.mark.asyncio
async def test_search_chat_requested_count_truncates_cards(monkeypatch):
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"intent": "search", "requested_count": 2, "pool_scope": "active",
                    "conditions": [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}],
                    "reason": "要 2 个"}

    class FakeEmbedder:
        async def embed(self, texts):
            return [[0.1] * 1024 for _ in texts]

    async def fake_get_llm(db, ws):
        return FakeLLM()

    async def fake_get_embedder(db, ws):
        return FakeEmbedder()

    monkeypatch.setattr("app.services.search.flow._get_llm", fake_get_llm)
    monkeypatch.setattr("app.services.search.flow._get_embedder", fake_get_embedder)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "rc@b.com", "password": "secret123", "nickname": "R"})
        token = (await c.post("/api/v1/auth/login", json={"email": "rc@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "RC-WS"}, headers=h)).json()["id"]
        async with SessionLocal() as db:
            for i in range(3):
                db.add(Candidate(workspace_id=ws_id, status=CandidateStatus.active, name=f"候选人{i}",
                                 structured_data={"skills": ["Java"]}, search_text="Java 支付"))
            await db.commit()
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "Java", "stream": False}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert len(body["cards"]) == 2
        assert "2 位" in body["summary"]


@pytest.mark.asyncio
async def test_load_context_falls_back_across_refusal():

    from app.api.search_chat import _load_context
    from app.core.database import SessionLocal
    from app.models import Conversation, Message, User, Workspace
    from app.services.search.context import serialize_context

    async with SessionLocal() as db:
        owner = User(email="ctx-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="ctx-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        conv = Conversation(user_id=owner.id, workspace_id=ws.id, knowledge_base_id=None, title="ctx")
        db.add(conv)
        await db.flush()
        ctx = {"conditions": [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}],
               "pool_scope": "active", "requested_count": None}
        db.add(Message(conversation_id=conv.id, role="assistant", content="找到 1 位",
                       sources=[{"type": "context", "payload": serialize_context(ctx)}]))
        db.add(Message(conversation_id=conv.id, role="assistant", content="写请求不执行", sources=[]))
        await db.commit()
        loaded = await _load_context(db, conv.id)
        assert loaded is not None
        assert loaded["conditions"][0]["field"] == "skills"


@pytest.mark.asyncio
async def test_search_chat_streams_job_candidates(monkeypatch):
    async def fake_run_search_flow(db, *, workspace_id, actor_role, actor_id, utterance, prior_context):
        from app.services.search.flow import SearchOutcome
        return SearchOutcome(intent="job_search", cards=[], summary="找到 2 个名称相近的在招职位，请选择：",
                             context={"job_candidates": [{"job_id": 1, "name": "前端开发工程师", "city": "杭州", "headcount": 2, "salary_range": None}]},
                             job_candidates=[{"job_id": 1, "name": "前端开发工程师", "city": "杭州", "headcount": 2, "salary_range": None},
                                             {"job_id": 2, "name": "前端开发工程师", "city": "上海", "headcount": 3, "salary_range": None}])

    monkeypatch.setattr("app.api.search_chat.run_search_flow", fake_run_search_flow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "sjc@b.com", "password": "secret123", "nickname": "S"})
        token = (await c.post("/api/v1/auth/login", json={"email": "sjc@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "SJC-WS"}, headers=h)).json()["id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "我要前端岗位的简历", "stream": True}, headers=h)
        assert r.status_code == 200
        body = r.text
        assert '"job_candidates"' in body or "job_candidates" in body
        assert '"job_id": 2' in body


@pytest.mark.asyncio
async def test_search_chat_returns_statistics_card(monkeypatch):
    async def fake_run_search_flow(db, *, workspace_id, actor_role, actor_id, utterance, prior_context):
        from app.services.search.flow import SearchOutcome
        return SearchOutcome(intent="statistics", cards=[], summary="人才库中共有 2 位候选人符合条件。城市分布：杭州 1、上海 1。",
                             context=None,
                             statistics={"count": 2, "dimension": "city",
                                         "distribution": [{"key": "杭州", "count": 1}, {"key": "上海", "count": 1}]})

    monkeypatch.setattr("app.api.search_chat.run_search_flow", fake_run_search_flow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "stc@b.com", "password": "secret123", "nickname": "S"})
        token = (await c.post("/api/v1/auth/login", json={"email": "stc@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "STC-WS"}, headers=h)).json()["id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "人才库有多少 Java 候选人？城市分布？", "stream": False}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "statistics"
        assert body["statistics"]["count"] == 2
        assert body["statistics"]["dimension"] == "city"


@pytest.mark.asyncio
async def test_search_chat_streams_statistics_event(monkeypatch):
    async def fake_run_search_flow(db, *, workspace_id, actor_role, actor_id, utterance, prior_context):
        from app.services.search.flow import SearchOutcome
        return SearchOutcome(intent="statistics", cards=[], summary="共有 1 位。", context=None,
                             statistics={"count": 1, "dimension": None, "distribution": []})

    monkeypatch.setattr("app.api.search_chat.run_search_flow", fake_run_search_flow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "sts@b.com", "password": "secret123", "nickname": "S"})
        token = (await c.post("/api/v1/auth/login", json={"email": "sts@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "STS-WS"}, headers=h)).json()["id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "有多少人？", "stream": True}, headers=h)
        assert r.status_code == 200
        assert '"type": "statistics"' in r.text
        assert '"count": 1' in r.text


@pytest.mark.asyncio
async def test_search_chat_model_failure_contract(monkeypatch):
    from app.services.model_client import ModelCallError

    async def fake_run_search_flow(db, *, workspace_id, actor_role, actor_id, utterance, prior_context):
        raise ModelCallError("模型服务不可用", retryable=True)

    monkeypatch.setattr("app.api.search_chat.run_search_flow", fake_run_search_flow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "mfe@b.com", "password": "secret123", "nickname": "M"})
        token = (await c.post("/api/v1/auth/login", json={"email": "mfe@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "MFE-WS"}, headers=h)).json()["id"]

        r = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                         json={"message": "找 Java", "stream": False}, headers=h)
        assert r.status_code == 502
        assert "模型" in r.json()["message"]

        r2 = await c.post(f"/api/v1/workspaces/{ws_id}/search-chat",
                          json={"message": "找 Java", "stream": True}, headers=h)
        assert r2.status_code == 200
        assert '"code": "MODEL_ERROR"' in r2.text
