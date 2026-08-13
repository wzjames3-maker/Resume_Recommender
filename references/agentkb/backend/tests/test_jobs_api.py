import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

_PARSED = {
    "conditions": [
        {"field": "skills", "op": "contains", "value": ["Vue"], "logic": "AND", "missing_policy": "exclude"},
    ],
    "evidence": {"skills": {"locator": "精通 Vue", "reason": ""}},
    "reason": "",
}


def _patch_llm(monkeypatch):
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return _PARSED

    async def fake_get_llm(db, ws):
        return FakeLLM()

    monkeypatch.setattr("app.api.jobs._get_llm", fake_get_llm)


async def _seed_active_candidate(ws_id: int):
    import uuid

    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateEmbedding,
        CandidateRevision,
        CandidateStatus,
    )

    run_id = f"ja-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as db:
        cand = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                         structured_data={"skills": ["Vue"], "years_experience": 6}, search_text="Vue")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id=run_id, revision_id=f"{run_id}:rev1",
                                candidate_json={"skills": ["Vue"]}, evidence={},
                                profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        db.add(CandidateEmbedding(candidate_id=cand.id, revision_id=f"{run_id}:rev1", segment="work",
                                  text="Vue", embedding=[0.1] * 1024))
        await db.commit()


@pytest.mark.asyncio
async def test_create_job_as_owner_returns_match_count(monkeypatch):
    _patch_llm(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "jobapi@b.com", "password": "secret123", "nickname": "J"})
        token = (await c.post("/api/v1/auth/login", json={"email": "jobapi@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "JOB-API-WS"}, headers=h)).json()["id"]
        await _seed_active_candidate(ws_id)
        r = await c.post(f"/api/v1/workspaces/{ws_id}/jobs", headers=h, json={
            "name": "前端开发工程师", "description": "5 年经验，精通 Vue",
            "headcount": 2, "city": "杭州", "salary_range": "25-40k"})
        assert r.status_code == 200
        body = r.json()
        assert body["job"]["name"] == "前端开发工程师"
        assert body["match_count"] == 1
        assert "可能匹配" in body["match_prompt"]
        r2 = await c.get(f"/api/v1/workspaces/{ws_id}/jobs/{body['job']['job_id']}", headers=h)
        assert r2.status_code == 200
        assert r2.json()["requirement"]["conditions"][0]["value"] == ["Vue"]
        assert r2.json()["job"]["status"] == "open"


@pytest.mark.asyncio
async def test_edit_and_override_require_admin(monkeypatch):
    _patch_llm(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "jb-owner@b.com", "password": "secret123", "nickname": "O"})
        ot = (await c.post("/api/v1/auth/login", json={"email": "jb-owner@b.com", "password": "secret123"})).json()["access_token"]
        oh = {"Authorization": f"Bearer {ot}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "JB-WS"}, headers=oh)).json()["id"]
        job_id = (await c.post(f"/api/v1/workspaces/{ws_id}/jobs", headers=oh, json={
            "name": "后端开发", "description": "3 年 Java", "headcount": 1, "city": None, "salary_range": None})).json()["job"]["job_id"]

        await c.post("/api/v1/auth/register", json={"email": "jb-member@b.com", "password": "secret123", "nickname": "M"})
        mt = (await c.post("/api/v1/auth/login", json={"email": "jb-member@b.com", "password": "secret123"})).json()["access_token"]
        mh = {"Authorization": f"Bearer {mt}"}
        await c.post(f"/api/v1/workspaces/{ws_id}/members", headers=oh, json={"email": "jb-member@b.com", "role": "member"})

        # member 编辑/关闭 403
        r = await c.patch(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}", headers=mh, json={
            "base_revision_id": 1, "status": "closed"})
        assert r.status_code == 403
        r = await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/overrides", headers=mh, json={
            "base_revision_id": 1, "field_path": "skills", "action": "clear"})
        assert r.status_code == 403

        # owner override + 关闭
        detail = (await c.get(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}", headers=oh)).json()
        base = detail["job"]["latest_revision_id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/overrides", headers=oh, json={
            "base_revision_id": base, "field_path": "skills", "action": "override",
            "after_value": {"field": "skills", "op": "contains", "value": ["Java", "Spring"], "logic": "AND", "missing_policy": "exclude"}})
        assert r.status_code == 200
        assert r.json()["conditions"][0]["value"] == ["Java", "Spring"]

        r = await c.patch(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}", headers=oh, json={
            "base_revision_id": base, "status": "closed"})
        assert r.status_code == 200
        assert r.json()["job"]["status"] == "closed"


@pytest.mark.asyncio
async def test_job_matches_returns_candidates(monkeypatch):
    _patch_llm(monkeypatch)

    class FakeEmbedder:
        async def embed(self, texts):
            return [[0.1] * 1024 for _ in texts]

    async def fake_get_embedder(db, ws):
        return FakeEmbedder()

    async def fake_get_rerank(db, ws):
        from app.services.model_client import ModelCallError
        raise ModelCallError("no rerank", retryable=False)

    monkeypatch.setattr("app.api.jobs._get_embedder", fake_get_embedder)
    monkeypatch.setattr("app.api.jobs._get_rerank", fake_get_rerank)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "jm-owner@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "jm-owner@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "JM-WS"}, headers=h)).json()["id"]
        await _seed_active_candidate(ws_id)
        job_id = (await c.post(f"/api/v1/workspaces/{ws_id}/jobs", headers=h, json={
            "name": "前端", "description": "精通 Vue", "headcount": 1, "city": None, "salary_range": None})).json()["job"]["job_id"]
        r = await c.get(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/matches", headers=h)
        assert r.status_code == 200
        assert r.json()["items"] and r.json()["items"][0]["name"] == "张三"

@pytest.mark.asyncio
async def test_override_rejects_secondary_field_path(monkeypatch):
    _patch_llm(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "sf-owner@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "sf-owner@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "SF-WS"}, headers=h)).json()["id"]
        job_id = (await c.post(f"/api/v1/workspaces/{ws_id}/jobs", headers=h, json={
            "name": "前端", "description": "精通 Vue", "headcount": 1, "city": None, "salary_range": None})).json()["job"]["job_id"]
        detail = (await c.get(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}", headers=h)).json()
        base = detail["job"]["latest_revision_id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/jobs/{job_id}/overrides", headers=h, json={
            "base_revision_id": base, "field_path": "expected_city", "action": "clear"})
        assert r.status_code == 400
