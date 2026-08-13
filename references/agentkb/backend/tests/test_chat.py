import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _email() -> str:
    return f"chat{uuid.uuid4().hex[:10]}@test.dev"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _new_user(c: AsyncClient) -> str:
    email = _email()
    r = await c.post("/api/v1/auth/register", json={"email": email, "password": "secret123", "nickname": email[:8]})
    assert r.status_code == 201
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200
    return r.json()["access_token"]


async def _create_ws(c: AsyncClient, token: str, name: str = "WS") -> int:
    r = await c.post("/api/v1/workspaces", json={"name": name}, headers=_auth(token))
    assert r.status_code == 201
    return r.json()["id"]


async def _create_kb(c: AsyncClient, token: str, ws_id: int, name: str = "KB") -> dict:
    r = await c.post(f"/api/v1/workspaces/{ws_id}/knowledge-bases", json={"name": name}, headers=_auth(token))
    assert r.status_code == 201
    return r.json()


async def _chat(c: AsyncClient, token: str, kb_id: int, message: str, conversation_id: int | None = None) -> tuple[int, str]:
    body = {"knowledge_base_id": kb_id, "message": message, "stream": True}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    async with c.stream("POST", "/api/v1/chat", json=body, headers=_auth(token)) as resp:
        lines = [line async for line in resp.aiter_lines()]
        return resp.status_code, "\n".join(lines)


def _parse_sse(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_chat_stream_returns_sse():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        status, body = await _chat(c, token, kb["id"], "你好")
        assert status == 200
        assert "data:" in body


@pytest.mark.asyncio
async def test_chat_sse_event_order_and_structure():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        status, body = await _chat(c, token, kb["id"], "你好")
        assert status == 200
        events = _parse_sse(body)
        assert [e["type"] for e in events] == ["sources", "token", "done"]
        assert events[0]["sources"] == []
        assert events[1]["content"] == "未在知识库中找到相关内容。"
        assert events[2]["token_count"] == len(events[1]["content"])
        assert events[2]["conversation_id"] > 0
        assert events[2]["message_id"] > 0


@pytest.mark.asyncio
async def test_chat_sources_reference_retrieved_chunks(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        content = "机器学习基础是人工智能的核心课程。".encode()
        r = await c.post(
            f"/api/v1/knowledge-bases/{kb['id']}/documents",
            files={"file": ("ml.txt", content, "text/plain")},
            headers=_auth(token),
        )
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.tasks.parse_document import _run
        await _run(doc_id)

        status, body = await _chat(c, token, kb["id"], "机器学习基础")
        assert status == 200
        events = _parse_sse(body)
        sources = events[0]["sources"]
        assert len(sources) >= 1
        assert all({"chunk_id", "document_id", "filename", "content", "score"} <= s.keys() for s in sources)
        assert all(s["filename"] == "ml.txt" for s in sources)
        assert all(s["content"] == content.decode() for s in sources)
        assert all(0.0 <= s["score"] <= 1.0 for s in sources)
        assert all(s["document_id"] == doc_id for s in sources)
        assert events[1]["content"].startswith("根据知识库内容：")
        assert events[2]["message_id"] > 0


@pytest.mark.asyncio
async def test_chat_other_users_conversation_returns_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token_a = await _new_user(c)
        token_b = await _new_user(c)
        ws_id = await _create_ws(c, token_a)
        kb = await _create_kb(c, token_a, ws_id)
        _, body = await _chat(c, token_a, kb["id"], "第一条消息")
        conv_id = _parse_sse(body)[-1]["conversation_id"]
        status, _ = await _chat(c, token_b, kb["id"], "越权访问", conv_id)
        assert status == 404


@pytest.mark.asyncio
async def test_chat_conversation_kb_mismatch_returns_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb1 = await _create_kb(c, token, ws_id, name="KB1")
        kb2 = await _create_kb(c, token, ws_id, name="KB2")
        _, body = await _chat(c, token, kb1["id"], "第一条消息")
        conv_id = _parse_sse(body)[-1]["conversation_id"]
        status, _ = await _chat(c, token, kb2["id"], "错库提问", conv_id)
        assert status == 404


@pytest.mark.asyncio
async def test_chat_unknown_conversation_returns_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        status, _ = await _chat(c, token, kb["id"], "不存在的会话", conversation_id=999999)
        assert status == 404


@pytest.mark.asyncio
async def test_chat_stream_false_returns_json(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await c.post("/api/v1/chat", json={"knowledge_base_id": kb["id"], "message": "你好", "stream": False}, headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        for key in ("answer", "sources", "token_count", "conversation_id", "message_id"):
            assert key in data
        assert data["answer"] == "未在知识库中找到相关内容。"
        assert data["sources"] == []
        assert data["token_count"] == len(data["answer"])
        assert data["conversation_id"] > 0
        assert data["message_id"] > 0


@pytest.mark.asyncio
async def test_chat_empty_message_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await c.post("/api/v1/chat", json={"knowledge_base_id": kb["id"], "message": ""}, headers=_auth(token))
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_chat_sse_emits_error_event_on_failure(monkeypatch):
    from sqlalchemy import text

    from app.core.database import SessionLocal

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    msg_text = "触发异常的提问"
    monkeypatch.setattr("app.api.chat.hybrid_search", _boom)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        status, body = await _chat(c, token, kb["id"], msg_text)
        assert status == 200
        events = _parse_sse(body)
        assert events[-1]["type"] == "error"
        assert events[-1]["code"] == "INTERNAL_ERROR"
        assert "boom" not in events[-1]["message"]
        # 不产生孤儿 assistant 消息：仅存在用户消息
        async with SessionLocal() as db:
            rows = await db.execute(text("SELECT role FROM messages WHERE content = :c"), {"c": msg_text})
            roles = [r[0] for r in rows.all()]
        assert roles == ["user"]


@pytest.mark.asyncio
async def test_removed_member_cannot_access_conversation(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        owner_email = f"chat{uuid.uuid4().hex[:10]}@test.dev"
        r = await c.post("/api/v1/auth/register", json={"email": owner_email, "password": "secret123", "nickname": "O"})
        assert r.status_code == 201
        r = await c.post("/api/v1/auth/login", json={"email": owner_email, "password": "secret123"})
        owner_token = r.json()["access_token"]
        ws_id = await _create_ws(c, owner_token)
        kb = await _create_kb(c, owner_token, ws_id)

        member_email = f"chat{uuid.uuid4().hex[:10]}@test.dev"
        r = await c.post("/api/v1/auth/register", json={"email": member_email, "password": "secret123", "nickname": "M"})
        assert r.status_code == 201
        r = await c.post("/api/v1/auth/login", json={"email": member_email, "password": "secret123"})
        member_token = r.json()["access_token"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/members", json={"email": member_email, "role": "member"}, headers=_auth(owner_token))
        member_id = r.json()["user_id"]

        _, body = await _chat(c, member_token, kb["id"], "A 的消息")
        conv_id = _parse_sse(body)[-1]["conversation_id"]

        r = await c.delete(f"/api/v1/workspaces/{ws_id}/members/{member_id}", headers=_auth(owner_token))
        assert r.status_code == 204

        assert (await c.get(f"/api/v1/conversations/{conv_id}/messages", headers=_auth(member_token))).status_code == 404
        assert (await c.delete(f"/api/v1/conversations/{conv_id}", headers=_auth(member_token))).status_code == 404