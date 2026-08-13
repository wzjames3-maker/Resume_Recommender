import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _email() -> str:
    return f"kb{uuid.uuid4().hex[:10]}@test.dev"


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


async def _create_kb(c: AsyncClient, token: str, ws_id: int, name: str = "KB", **overrides) -> dict:
    body = {"name": name, "chunk_size": 512, "chunk_overlap": 64, **overrides}
    r = await c.post(f"/api/v1/workspaces/{ws_id}/knowledge-bases", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()


async def _upload(c: AsyncClient, token: str, kb_id: int, filename: str = "test.txt", content: bytes = b"content", content_type: str = "text/plain"):
    return await c.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        files={"file": (filename, content, content_type)},
        headers=_auth(token),
    )


@pytest.mark.asyncio
async def test_create_and_list_knowledge_base():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        assert kb["chunk_size"] == 512 and kb["chunk_overlap"] == 64
        assert kb["embedding_model"] == "bge-m3"
        r = await c.get(f"/api/v1/workspaces/{ws_id}/knowledge-bases", headers=_auth(token))
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert kb["id"] in ids


@pytest.mark.asyncio
async def test_create_kb_overlap_ge_size_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        r = await c.post(f"/api/v1/workspaces/{ws_id}/knowledge-bases", json={"name": "KB", "chunk_size": 64, "chunk_overlap": 64}, headers=_auth(token))
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_kb_duplicate_name_conflict():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        await _create_kb(c, token, ws_id, name="重复")
        r = await c.post(f"/api/v1/workspaces/{ws_id}/knowledge-bases", json={"name": "重复"}, headers=_auth(token))
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_member_cannot_create_kb():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        member_email, member_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await c.post(f"/api/v1/workspaces/{ws_id}/members", json={"email": member_email, "role": "member"}, headers=_auth(owner_token))
        assert r.status_code == 201
        r = await c.post(f"/api/v1/workspaces/{ws_id}/knowledge-bases", json={"name": "KB"}, headers=_auth(member_token))
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_non_member_gets_404_on_kb():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        _, outsider_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        r = await c.post(f"/api/v1/workspaces/{ws_id}/knowledge-bases", json={"name": "KB"}, headers=_auth(outsider_token))
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_kb_detail_counts_documents_and_chunks(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"])
        assert r.status_code == 202
        r = await c.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        assert data["doc_count"] >= 1
        assert data["chunk_count"] >= 0


@pytest.mark.asyncio
async def test_update_kb_name_and_description():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await c.put(f"/api/v1/knowledge-bases/{kb['id']}", json={"name": "新名", "description": "新描述"}, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["name"] == "新名"
        assert r.json()["description"] == "新描述"


@pytest.mark.asyncio
async def test_update_kb_immutable_fields_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await c.put(f"/api/v1/knowledge-bases/{kb['id']}", json={"chunk_size": 800}, headers=_auth(token))
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_kb_cascades():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            _, token = await _new_user(c)
            ws_id = await _create_ws(c, token)
            kb = await _create_kb(c, token, ws_id)
            r = await _upload(c, token, kb["id"])
            assert r.status_code == 202
            r = await c.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=_auth(token))
            assert r.status_code == 204
            r = await c.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=_auth(token))
            assert r.status_code == 404
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_upload_document_returns_202_pending(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"])
        assert r.status_code == 202
        data = r.json()
        assert data["status"] == "pending"
        assert data["document_id"] > 0


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_type(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="evil.exe", content=b"x", content_type="application/x-msdownload")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_oversize(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    monkeypatch.setattr("app.api.documents.MAX_SIZE", 10)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], content=b"x" * 20)
        assert r.status_code == 413


@pytest.mark.asyncio
async def test_upload_path_traversal_sanitized(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    monkeypatch.setattr("app.api.documents.UPLOAD_DIR", str(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="../../逃逸.txt", content=b"hi", content_type="text/plain")
        assert r.status_code == 202
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert "逃逸" in files[0].name
        assert files[0].read_bytes() == b"hi"


@pytest.mark.asyncio
async def test_member_cannot_upload_document(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        member_email, member_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        kb = await _create_kb(c, owner_token, ws_id)
        r = await c.post(f"/api/v1/workspaces/{ws_id}/members", json={"email": member_email, "role": "member"}, headers=_auth(owner_token))
        assert r.status_code == 201
        r = await _upload(c, member_token, kb["id"])
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_document_list_and_detail(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"])
        doc_id = r.json()["document_id"]
        r = await c.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=_auth(token))
        assert r.status_code == 200
        assert any(d["id"] == doc_id and d["status"] == "pending" for d in r.json()["items"])
        r = await c.get(f"/api/v1/documents/{doc_id}", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["filename"] == "test.txt"


@pytest.mark.asyncio
async def test_member_can_read_chunks(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, owner_token = await _new_user(c)
        member_email, member_token = await _new_user(c)
        ws_id = await _create_ws(c, owner_token)
        kb = await _create_kb(c, owner_token, ws_id)
        r = await c.post(f"/api/v1/workspaces/{ws_id}/members", json={"email": member_email, "role": "member"}, headers=_auth(owner_token))
        assert r.status_code == 201
        r = await _upload(c, owner_token, kb["id"], filename="long.txt", content=b"word " * 500, content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.tasks.parse_document import _run
        await _run(doc_id)
        r = await c.get(f"/api/v1/documents/{doc_id}/chunks", headers=_auth(member_token))
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert all("content" in item for item in data["items"])


@pytest.mark.asyncio
async def test_parse_task_state_machine_ready(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        content = "第一段。\n\n第二段内容。\n\n第三段内容继续。".encode()
        r = await _upload(c, token, kb["id"], filename="hello.txt", content=content, content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.tasks.parse_document import _run
        await _run(doc_id)
        r = await c.get(f"/api/v1/documents/{doc_id}", headers=_auth(token))
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ready"
        assert data["chunk_count"] >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("resume.pdf", b"%PDF-1.7\nplaceholder", "application/pdf"),
        (
            "resume.docx",
            b"PK\x03\x04placeholder",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
async def test_unimplemented_document_formats_are_failed(monkeypatch, filename, content, content_type):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename=filename, content=content, content_type=content_type)
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.tasks.parse_document import _run

        await _run(doc_id)
        r = await c.get(f"/api/v1/documents/{doc_id}", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["status"] == "failed"
        assert "暂不支持解析" in r.json()["error_message"]


@pytest.mark.asyncio
async def test_parse_task_respects_kb_chunk_config(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id, chunk_size=64, chunk_overlap=8)
        content = "\n\n".join(["内容内容内容内容内容内容内容内容内容内容" for _ in range(30)])
        r = await _upload(c, token, kb["id"], filename="cfg.txt", content=content.encode("utf-8"), content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.tasks.parse_document import _run
        await _run(doc_id)
        r = await c.get(f"/api/v1/documents/{doc_id}/chunks", headers=_auth(token), params={"page_size": 100})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 2
        assert all(len(item["content"]) <= 64 + 8 for item in data["items"])


@pytest.mark.asyncio
async def test_parse_task_failed_on_missing_file(monkeypatch, tmp_path):
    from app.tasks.parse_document import _run
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="gone.txt", content=b"whatever", content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.core.database import SessionLocal
        from app.models import Document
        from app.tasks.parse_document import _run
        async with SessionLocal() as db:
            doc = await db.get(Document, doc_id)
            doc.storage_key = str(tmp_path / "not-exist.txt")
            await db.commit()
        await _run(doc_id)
        import asyncio
        await asyncio.sleep(0)
        async with SessionLocal() as db:
            doc = await db.get(Document, doc_id)
            assert doc.status.value == "failed"
            assert doc.error_message


@pytest.mark.asyncio
async def test_retry_failed_document(monkeypatch):
    calls = []
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: calls.append(doc_id))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="x.txt", content=b"abc", content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.core.database import SessionLocal
        from app.models import Document
        async with SessionLocal() as db:
            doc = await db.get(Document, doc_id)
            doc.status = "failed"
            await db.commit()
        r = await c.post(f"/api/v1/documents/{doc_id}/retry", headers=_auth(token))
        assert r.status_code == 202
        assert doc_id in calls


@pytest.mark.asyncio
async def test_retry_non_failed_conflict(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="y.txt", content=b"abc", content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        r = await c.post(f"/api/v1/documents/{doc_id}/retry", headers=_auth(token))
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_delete_document(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="del.txt", content=b"abc", content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        r = await c.delete(f"/api/v1/documents/{doc_id}", headers=_auth(token))
        assert r.status_code == 204
        r = await c.get(f"/api/v1/documents/{doc_id}", headers=_auth(token))
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_processing_conflict(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="proc.txt", content=b"abc", content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.core.database import SessionLocal
        from app.models import Document
        async with SessionLocal() as db:
            doc = await db.get(Document, doc_id)
            doc.status = "processing"
            await db.commit()
        r = await c.delete(f"/api/v1/documents/{doc_id}", headers=_auth(token))
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_list_documents_invalid_status_400(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await c.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", params={"status": "bogus"}, headers=_auth(token))
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_documents_valid_status_filter(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        await _upload(c, token, kb["id"])
        r = await c.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", params={"status": "pending"}, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["total"] >= 1


@pytest.mark.asyncio
async def test_delete_document_removes_physical_file(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    monkeypatch.setattr("app.api.documents.UPLOAD_DIR", str(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="del.txt", content=b"abc", content_type="text/plain")
        assert r.status_code == 202
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        file_path = files[0]
        doc_id = r.json()["document_id"]
        r = await c.delete(f"/api/v1/documents/{doc_id}", headers=_auth(token))
        assert r.status_code == 204
        assert not file_path.exists()


@pytest.mark.asyncio
async def test_delete_document_missing_file_still_ok(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="gone.txt", content=b"abc", content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.core.database import SessionLocal
        from app.models import Document
        async with SessionLocal() as db:
            doc = await db.get(Document, doc_id)
            doc.storage_key = str(tmp_path / "not-exist.txt")
            await db.commit()
        r = await c.delete(f"/api/v1/documents/{doc_id}", headers=_auth(token))
        assert r.status_code == 204
        r = await c.get(f"/api/v1/documents/{doc_id}", headers=_auth(token))
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_kb_processing_conflict(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="proc.txt", content=b"abc", content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.core.database import SessionLocal
        from app.models import Document
        async with SessionLocal() as db:
            doc = await db.get(Document, doc_id)
            doc.status = "processing"
            await db.commit()
        r = await c.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=_auth(token))
        assert r.status_code == 409
        r = await c.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=_auth(token))
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_delete_kb_removes_physical_files(monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    monkeypatch.setattr("app.api.documents.UPLOAD_DIR", str(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="a.txt", content=b"a", content_type="text/plain")
        assert r.status_code == 202
        r = await _upload(c, token, kb["id"], filename="b.txt", content=b"b", content_type="text/plain")
        assert r.status_code == 202
        assert len(list(tmp_path.iterdir())) == 2
        r = await c.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=_auth(token))
        assert r.status_code == 204
        assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_page_zero_clamped(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await c.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", params={"page": 0}, headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["page"] == 1


@pytest.mark.asyncio
async def test_read_limited_rejects_by_declared_size():
    from fastapi import HTTPException

    from app.api.documents import _read_limited

    class _FakeFile:
        size = 11

        async def read(self, n):
            raise AssertionError("不应在声明大小超限时读取内容")

    with pytest.raises(HTTPException) as ei:
        await _read_limited(_FakeFile(), 10)
    assert ei.value.status_code == 413


@pytest.mark.asyncio
async def test_read_limited_aborts_mid_stream_when_no_size():
    from fastapi import HTTPException

    from app.api.documents import _read_limited

    class _FakeFile:
        size = None

        def __init__(self):
            self._chunks = [b"a" * 1024, b"b" * 1024]
            self._i = 0

        async def read(self, n):
            if self._i >= len(self._chunks):
                return b""
            c = self._chunks[self._i]
            self._i += 1
            return c

    with pytest.raises(HTTPException) as ei:
        await _read_limited(_FakeFile(), 1500)
    assert ei.value.status_code == 413


@pytest.mark.asyncio
async def test_get_doc_for_member_orphan_kb_returns_404():
    from fastapi import HTTPException

    from app.models import Document, KnowledgeBase
    from app.services.kb_service import get_doc_for_member

    class _FakeDB:
        async def get(self, model, pk):
            if model is KnowledgeBase:
                return None
            return Document(knowledge_base_id=999)

    with pytest.raises(HTTPException) as ei:
        await get_doc_for_member(_FakeDB(), 1, None)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_chunk_embedding_dim_matches_model(monkeypatch):
    monkeypatch.setattr("app.api.documents.parse_document.delay", lambda doc_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        _, token = await _new_user(c)
        ws_id = await _create_ws(c, token)
        kb = await _create_kb(c, token, ws_id)
        r = await _upload(c, token, kb["id"], filename="dim.txt", content=b"hello world", content_type="text/plain")
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        from app.tasks.parse_document import _run
        await _run(doc_id)
        from sqlalchemy import select

        from app.core.database import SessionLocal
        from app.models import EMBEDDING_DIM, Chunk
        async with SessionLocal() as db:
            rows = await db.execute(select(Chunk).where(Chunk.document_id == doc_id))
            chunks = rows.scalars().all()
        assert len(chunks) >= 1
        assert all(len(ch.embedding) == EMBEDDING_DIM for ch in chunks)


def test_parse_document_task_survives_cross_loop():
    from app.tasks.parse_document import parse_document
    # 本文件前面的异步用例已在 pytest 会话 loop 上占用过连接池；真实 worker 中
    # 每次任务用 asyncio.run 新建 loop，若池中残留旧 loop 连接会跨 loop 崩溃。
    # 修复后任务前后各 dispose 一次，重复执行也不应报错、不泄漏连接。
    parse_document.run(999999999)
    parse_document.run(999999999)