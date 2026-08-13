import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_register_login_flow():
    email = f"auth-{uuid.uuid4().hex}@b.com"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/auth/register", json={"email": email, "password": "secret123", "nickname": "A"})
        assert r.status_code == 201
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data and "refresh_token" in data
        r = await c.get("/api/v1/users/me", headers={"Authorization": f"Bearer {data['access_token']}"})
        assert r.status_code == 200
        assert r.json()["email"] == email


@pytest.mark.asyncio
async def test_logout_cannot_revoke_other_users_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        email_a = f"auth-{uuid.uuid4().hex}@b.com"
        email_b = f"auth-{uuid.uuid4().hex}@b.com"
        for email in (email_a, email_b):
            r = await c.post("/api/v1/auth/register", json={"email": email, "password": "secret123", "nickname": "X"})
            assert r.status_code == 201
        ra = await c.post("/api/v1/auth/login", json={"email": email_a, "password": "secret123"})
        rb = await c.post("/api/v1/auth/login", json={"email": email_b, "password": "secret123"})
        token_a = ra.json()["access_token"]
        refresh_b = rb.json()["refresh_token"]
        r = await c.post("/api/v1/auth/logout", json={"refresh_token": refresh_b}, headers={"Authorization": f"Bearer {token_a}"})
        assert r.status_code == 403
        assert (await c.post("/api/v1/auth/refresh", json={"refresh_token": refresh_b})).status_code == 200


@pytest.mark.asyncio
async def test_expired_access_token_returns_token_expired():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        payload = {"sub": "1", "type": "access", "exp": datetime.now(UTC) - timedelta(minutes=1)}
        expired = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        r = await c.get("/api/v1/users/me", headers={"Authorization": f"Bearer {expired}"})
        assert r.status_code == 401
        assert r.json()["code"] == "TOKEN_EXPIRED"


@pytest.mark.asyncio
async def test_malformed_token_claims_return_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        malformed_access = jwt.encode({"sub": "not-an-integer", "type": "access",
                                      "exp": datetime.now(UTC) + timedelta(minutes=1)},
                                     settings.jwt_secret, algorithm="HS256")
        response = await c.get("/api/v1/users/me", headers={"Authorization": f"Bearer {malformed_access}"})
        assert response.status_code == 401

        malformed_refresh = jwt.encode({"type": "refresh", "exp": datetime.now(UTC) + timedelta(minutes=1)},
                                       settings.jwt_secret, algorithm="HS256")
        response = await c.post("/api/v1/auth/refresh", json={"refresh_token": malformed_refresh})
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_store_unavailable_returns_503(monkeypatch):
    from app.core import token_store

    async def boom(jti):
        raise token_store.TokenStoreUnavailable("redis down")

    monkeypatch.setattr(token_store, "is_refresh_token_valid", boom)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        payload = {"sub": "1", "type": "refresh", "jti": "j-1",
                   "exp": datetime.now(UTC) + timedelta(minutes=1)}
        valid_token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        response = await c.post("/api/v1/auth/refresh", json={"refresh_token": valid_token})
        assert response.status_code == 503
