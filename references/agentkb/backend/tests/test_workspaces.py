import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _email() -> str:
    return f"u{uuid.uuid4().hex[:10]}@test.dev"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _new_user(c: AsyncClient) -> tuple[str, str]:
    email = _email()
    r = await c.post("/api/v1/auth/register", json={"email": email, "password": "secret123", "nickname": email[:8]})
    assert r.status_code == 201
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200
    return email, r.json()["access_token"]


async def _create_ws(c: AsyncClient, token: str, name: str = "WS") -> int:
    r = await c.post("/api/v1/workspaces", json={"name": name}, headers=_auth(token))
    assert r.status_code == 201
    return r.json()["id"]


async def _invite(c: AsyncClient, token: str, ws_id: int, email: str, role: str = "member"):
    return await c.post(
        f"/api/v1/workspaces/{ws_id}/members",
        json={"email": email, "role": role},
        headers=_auth(token),
    )


@pytest.mark.asyncio
async def test_create_and_list_workspace():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token, name="研发团队")
        r = await c.get("/api/v1/workspaces", headers=_auth(token))
        assert r.status_code == 200
        assert any(item["id"] == ws_id and item["name"] == "研发团队" and item["role"] == "owner" for item in r.json()["items"])


@pytest.mark.asyncio
async def test_owner_can_invite_member():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        member_email, _ = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await _invite(c, owner_token, ws_id, member_email, "member")
        assert r.status_code == 201
        data = r.json()
        assert data["email"] == member_email
        assert data["role"] == "member"


@pytest.mark.asyncio
async def test_invite_as_owner_role_forbidden():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        other_email, _ = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await _invite(c, owner_token, ws_id, other_email, "owner")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_invite():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        member_email, member_token = await _new_user(c)
        third_email, _ = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        assert (await _invite(c, owner_token, ws_id, member_email, "member")).status_code == 201
        r = await _invite(c, member_token, ws_id, third_email, "member")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_non_member_gets_404_cross_tenant():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        outsider_email, outsider_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await _invite(c, outsider_token, ws_id, outsider_email, "member")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_invite_unknown_email_returns_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await _invite(c, owner_token, ws_id, "nobody@test.dev")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_invite_existing_member_returns_409():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        member_email, _ = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        assert (await _invite(c, owner_token, ws_id, member_email, "member")).status_code == 201
        r = await _invite(c, owner_token, ws_id, member_email, "member")
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_admin_can_invite_member_but_not_promote_admin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        admin_email, admin_token = await _new_user(c)
        member_email, _ = await _new_user(c)
        admin_candidate_email, _ = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        assert (await _invite(c, owner_token, ws_id, admin_email, "admin")).status_code == 201
        assert (await _invite(c, admin_token, ws_id, member_email, "member")).status_code == 201
        r = await _invite(c, admin_token, ws_id, admin_candidate_email, "admin")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_integrity_error_race_mapped_to_409_handler():
    import json

    from sqlalchemy.exc import IntegrityError

    from app.main import integrity_error_handler

    class _Req:
        pass

    resp = await integrity_error_handler(_Req(), IntegrityError("INSERT ...", {}, Exception("duplicate key value violates unique constraint")))
    assert resp.status_code == 409
    payload = json.loads(resp.body)
    assert payload["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_workspace_detail_lists_members():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        owner_email, owner_token = await _new_user(c)
        member_email, _ = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        await _invite(c, owner_token, ws_id, member_email, "member")
        r = await c.get(f"/api/v1/workspaces/{ws_id}", headers=_auth(owner_token))
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "owner"
        emails = [m["email"] for m in data["members"]]
        assert owner_email in emails and member_email in emails


@pytest.mark.asyncio
async def test_workspace_detail_403_for_non_member():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        _, outsider_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await c.get(f"/api/v1/workspaces/{ws_id}", headers=_auth(outsider_token))
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_workspace_only_owner():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        member_email, member_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        await _invite(c, owner_token, ws_id, member_email, "member")
        assert (await c.delete(f"/api/v1/workspaces/{ws_id}", headers=_auth(member_token))).status_code == 403
        r = await c.delete(f"/api/v1/workspaces/{ws_id}", headers=_auth(owner_token))
        assert r.status_code == 204
        assert (await c.get(f"/api/v1/workspaces/{ws_id}", headers=_auth(owner_token))).status_code == 404


@pytest.mark.asyncio
async def test_update_member_role_and_remove():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        member_email, member_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await _invite(c, owner_token, ws_id, member_email, "member")
        member_id = r.json()["user_id"]
        r = await c.patch(f"/api/v1/workspaces/{ws_id}/members/{member_id}", json={"role": "admin"}, headers=_auth(owner_token))
        assert r.status_code == 200
        assert r.json()["role"] == "admin"
        assert (await c.patch(f"/api/v1/workspaces/{ws_id}/members/{member_id}", json={"role": "admin"}, headers=_auth(member_token))).status_code == 403
        r = await c.delete(f"/api/v1/workspaces/{ws_id}/members/{member_id}", headers=_auth(owner_token))
        assert r.status_code == 204
        assert (await c.patch(f"/api/v1/workspaces/{ws_id}/members/{member_id}", json={"role": "member"}, headers=_auth(owner_token))).status_code == 404


@pytest.mark.asyncio
async def test_update_owner_role_conflict():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await c.get(f"/api/v1/workspaces/{ws_id}", headers=_auth(owner_token))
        owner_user_id = next(m["user_id"] for m in r.json()["members"] if m["role"] == "owner")
        resp = await c.patch(f"/api/v1/workspaces/{ws_id}/members/{owner_user_id}", json={"role": "member"}, headers=_auth(owner_token))
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_member_role_rejects_owner():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        member_email, _ = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await _invite(c, owner_token, ws_id, member_email, "member")
        member_id = r.json()["user_id"]
        resp = await c.patch(f"/api/v1/workspaces/{ws_id}/members/{member_id}", json={"role": "owner"}, headers=_auth(owner_token))
        assert resp.status_code == 400
        detail = await c.get(f"/api/v1/workspaces/{ws_id}", headers=_auth(owner_token))
        member = next(m for m in detail.json()["members"] if m["user_id"] == member_id)
        assert member["role"] == "member"


@pytest.mark.asyncio
async def test_usage_returns_placeholder():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await c.get(f"/api/v1/workspaces/{ws_id}/usage", headers=_auth(owner_token))
        assert r.status_code == 200
        data = r.json()
        assert data["tokens_used_this_month"] == 0
        assert data["remaining"] == data["monthly_limit"]