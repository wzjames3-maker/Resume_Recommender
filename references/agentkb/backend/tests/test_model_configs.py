import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _email() -> str:
    return f"mc{uuid.uuid4().hex[:10]}@test.dev"


async def _setup(c: AsyncClient) -> tuple[str, int]:
    email = _email()
    r = await c.post("/api/v1/auth/register", json={"email": email, "password": "secret123", "nickname": "M"})
    assert r.status_code == 201
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r = await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)
    return email, r.json()["id"]


@pytest.mark.asyncio
async def test_model_config_crud_and_mask():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        email, ws_id = await _setup(c)
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/model-configs", json={
            # base_url 用公网 IP 字面量：沙箱 fake-IP DNS 使域名解析到私网段，会被 SSRF 网关拦截
            "model_type": "llm", "base_url": "https://1.1.1.1", "model_name": "deepseek-chat", "api_key": "sk-abcdefghijkl"
        }, headers=h)
        assert r.status_code == 201
        data = r.json()
        assert "sk-abcdefghijkl" not in data["key_prefix"]
        assert data["key_prefix"].startswith("sk-ab")
        assert data["model_config_revision"] == 1
        r = await c.get(f"/api/v1/workspaces/{ws_id}/model-configs", headers=h)
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_model_config_revision_increments_on_update():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        email, ws_id = await _setup(c)
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        body = {"model_type": "llm", "base_url": "https://1.1.1.1", "model_name": "gpt-4o", "api_key": "sk-newkey123456"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/model-configs", json=body, headers=h)
        assert r.status_code == 201
        assert r.json()["model_config_revision"] == 1
        r = await c.post(f"/api/v1/workspaces/{ws_id}/model-configs", json=body, headers=h)
        assert r.status_code == 201
        data = r.json()
        assert data["model_config_revision"] == 2
        assert data["key_prefix"].startswith("sk-new")
        assert "sk-newkey123456" not in data["key_prefix"]


@pytest.mark.asyncio
async def test_member_cannot_write_model_config():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        owner_email, ws_id = await _setup(c)
        r = await c.post("/api/v1/auth/login", json={"email": owner_email, "password": "secret123"})
        owner_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        member_email = _email()
        r = await c.post("/api/v1/auth/register", json={"email": member_email, "password": "secret123", "nickname": "Mem"})
        assert r.status_code == 201
        r = await c.post("/api/v1/auth/login", json={"email": member_email, "password": "secret123"})
        member_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/members", json={"email": member_email, "role": "member"}, headers=owner_h)
        assert r.status_code == 201
        r = await c.post(f"/api/v1/workspaces/{ws_id}/model-configs", json={
            "model_type": "embedding", "base_url": "https://1.1.1.1", "model_name": "e", "api_key": "sk-x"
        }, headers=member_h)
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_model_config_test_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        email, ws_id = await _setup(c)
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/model-configs", json={
            "model_type": "llm", "base_url": "https://1.1.1.1", "model_name": "qwen", "api_key": "sk-test123456"
        }, headers=h)
        assert r.status_code == 201
        r = await c.post(f"/api/v1/workspaces/{ws_id}/model-configs/llm/test", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["model_config_revision"] == 1


@pytest.mark.asyncio
async def test_crypto_roundtrip():
    from app.services.crypto import decrypt_secret, encrypt_secret
    plain = "sk-abcdefghijkl"
    enc = encrypt_secret(plain)
    assert enc != plain
    assert decrypt_secret(enc) == plain
    assert encrypt_secret(plain) != encrypt_secret(plain)


@pytest.mark.asyncio
async def test_outbound_gateway_blocks_private_ips():
    from app.services.outbound_gateway import validate_endpoint
    with pytest.raises(Exception):  # noqa: B017
        await validate_endpoint("http://127.0.0.1:8000/v1")
    with pytest.raises(Exception):  # noqa: B017
        await validate_endpoint("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(Exception):  # noqa: B017
        await validate_endpoint("http://192.168.1.1/v1")
    # 沙箱为 WSL fake-IP DNS：域名一律解析到 198.18.0.0/15 私网段，会被网关正确拦截，
    # 故正向用例改用公网 IP 字面量验证合法 HTTPS 端点放行。
    ok = await validate_endpoint("https://1.1.1.1/v1")
    assert ok is True


@pytest.mark.asyncio
async def test_outbound_gateway_blocks_cgnat_shared_address():
    from app.services.outbound_gateway import validate_endpoint
    # RFC 6598 100.64.0.0/10 共享地址段：is_global=False，必须被拦截
    with pytest.raises(Exception):  # noqa: B017
        await validate_endpoint("https://100.64.0.1/v1")
    with pytest.raises(Exception):  # noqa: B017
        await validate_endpoint("https://100.127.255.254/v1")


@pytest.mark.asyncio
async def test_outbound_gateway_rejects_non_numeric_port():
    from app.services.outbound_gateway import validate_endpoint
    with pytest.raises(ValueError):
        await validate_endpoint("https://a.com:abc/v1")


def test_jwt_secret_guard_rejects_placeholder_and_short_key():
    from pydantic import ValidationError

    from app.core.config import Settings
    valid_model_key = "0123456789abcdef" * 4
    with pytest.raises(ValidationError):
        Settings(jwt_secret="change-me", model_key_enc_key=valid_model_key)
    with pytest.raises(ValidationError):
        Settings(jwt_secret="short-key", model_key_enc_key=valid_model_key)
    s = Settings(jwt_secret="x" * 40, model_key_enc_key=valid_model_key)
    assert s.jwt_secret == "x" * 40


@pytest.mark.asyncio
async def test_model_config_rejects_invalid_type_and_empty_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        email, ws_id = await _setup(c)
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/model-configs", json={
            "model_type": "ollama", "base_url": "https://1.1.1.1", "model_name": "m", "api_key": "sk-x"
        }, headers=h)
        assert r.status_code == 400
        r = await c.post(f"/api/v1/workspaces/{ws_id}/model-configs", json={
            "model_type": "llm", "base_url": "https://1.1.1.1", "model_name": "m", "api_key": ""
        }, headers=h)
        assert r.status_code == 400