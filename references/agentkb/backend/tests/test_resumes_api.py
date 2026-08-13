import io

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_upload_resume_returns_runs(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "r@b.com", "password": "secret123", "nickname": "R"})
        token = (await c.post("/api/v1/auth/login", json={"email": "r@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        files = {"files": ("a.docx",  io.BytesIO(b"PK\x03\x04xx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/upload",
                         data={"upload_id": "up-1", "source_channel": "job_site"},
                         files=[("files", files["files"])], headers=h)
        assert r.status_code == 202
        assert r.json()["runs"]


@pytest.mark.asyncio
async def test_import_json_envelope(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "j@b.com", "password": "secret123", "nickname": "J"})
        token = (await c.post("/api/v1/auth/login", json={"email": "j@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        envelope = {
            "upload_id": "json-up-1",
            "schema_version": "resume-import/v1",
            "template_version": "2026-08-07.1",
            "source_channel": "referral",
            "referrer": "李四",
            "records": [{"name": "张三", "phone": "13800000000", "email": "a@b.com"}],
        }
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/import",
                         json=envelope, headers=h)
        assert r.status_code == 202
        assert "batch_id" in r.json() and len(r.json()["runs"]) == 1


@pytest.mark.asyncio
async def test_import_json_invalid_record_is_reported_without_aborting_batch(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "u@b.com", "password": "secret123", "nickname": "U"})
        token = (await c.post("/api/v1/auth/login", json={"email": "u@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        envelope = {
            "upload_id": "json-up-2",
            "schema_version": "resume-import/v1",
            "template_version": "2026-08-07.1",
            "source_channel": "referral",
            "records": [
                {"name": "张三", "fabricated_field": "x"},
                {"name": "李四", "skills": ["Python"]},
            ],
        }
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/import", json=envelope, headers=h)
        assert r.status_code == 202
        assert len(r.json()["runs"]) == 1
        assert r.json()["row_errors"] == [{"index": 0, "reason": "未知字段: ['fabricated_field']"}]


@pytest.mark.asyncio
async def test_upload_rejects_extension_signature_mismatch(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "m@b.com", "password": "secret123", "nickname": "M"})
        token = (await c.post("/api/v1/auth/login", json={"email": "m@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/upload",
                         data={"upload_id": "up-magic", "source_channel": "job_site"},
                         files=[("files", ("wrong.docx", io.BytesIO(b"%PDF-1.4"), "application/pdf"))], headers=h)
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_pdf(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "p@b.com", "password": "secret123", "nickname": "P"})
        token = (await c.post("/api/v1/auth/login", json={"email": "p@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/upload",
                         data={"upload_id": "up-pdf", "source_channel": "job_site"},
                         files=[("files", ("a.pdf", io.BytesIO(b"%PDF-1.4\ncontent"), "application/pdf"))], headers=h)
        assert r.status_code == 400
        assert "PDF" in r.json()["message"]


@pytest.mark.asyncio
async def test_upload_same_content_dedups_by_content_hash(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "d@b.com", "password": "secret123", "nickname": "D"})
        token = (await c.post("/api/v1/auth/login", json={"email": "d@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()

        def _files():
            return [("files", ("a.docx", io.BytesIO(b"PK\x03\x04xx"),
                               "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))]

        r1 = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/upload",
                          data={"upload_id": "up-d1", "source_channel": "job_site"}, files=_files(), headers=h)
        assert r1.status_code == 202
        first_run = r1.json()["runs"][0]
        # 同一业务输入（内容 hash + 渠道 + 模板）换 upload_id 重传 → 复用既有 run，不重复创建
        r2 = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/upload",
                          data={"upload_id": "up-d2", "source_channel": "job_site"}, files=_files(), headers=h)
        assert r2.status_code == 202
        assert r2.json()["runs"] == [first_run]
        assert r2.json()["duplicate"] is True


@pytest.mark.asyncio
async def test_import_json_records_exceed_limit(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "l@b.com", "password": "secret123", "nickname": "L"})
        token = (await c.post("/api/v1/auth/login", json={"email": "l@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        envelope = {
            "upload_id": "big-json",
            "schema_version": "resume-import/v1",
            "template_version": "2026-08-07.1",
            "source_channel": "referral",
            "records": [{"name": f"候选人{i}"} for i in range(101)],
        }
        r = await c.post(f"/api/v1/workspaces/{ws['id']}/resumes/import", json=envelope, headers=h)
        assert r.status_code == 400
        assert "上限" in r.json()["message"]


@pytest.mark.asyncio
async def test_member_cannot_read_hired_resume_run_or_ir(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateStatus,
        ParseRun,
        ParseRunStatus,
        ResumeFile,
        ResumeIR,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "acl-r-owner@b.com", "password": "secret123", "nickname": "O"})
        owner_token = (await c.post("/api/v1/auth/login", json={"email": "acl-r-owner@b.com", "password": "secret123"})).json()["access_token"]
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "ACL-R-WS"}, headers=owner_headers)).json()["id"]
        await c.post("/api/v1/auth/register", json={"email": "acl-r-member@b.com", "password": "secret123", "nickname": "M"})
        member_token = (await c.post("/api/v1/auth/login", json={"email": "acl-r-member@b.com", "password": "secret123"})).json()["access_token"]
        member_headers = {"Authorization": f"Bearer {member_token}"}
        await c.post(f"/api/v1/workspaces/{ws_id}/members", headers=owner_headers,
                     json={"email": "acl-r-member@b.com", "role": "member"})

        async with SessionLocal() as db:
            candidate = Candidate(workspace_id=ws_id, status=CandidateStatus.hired, name="员工",
                                  structured_data={}, search_text="")
            db.add(candidate)
            await db.flush()
            run = ParseRun(run_id="acl-r-run-1", workspace_id=ws_id, upload_id="acl-r-up",
                           source_channel="job_site", format="docx", file_hash="h" * 64,
                           file_path="/tmp/x", file_size=1, parser_version="0.1.0",
                           status=ParseRunStatus.succeeded)
            db.add(run)
            await db.flush()
            db.add(ResumeFile(run_id=run.run_id, candidate_id=candidate.id, file_hash="h" * 64,
                              storage_key="/tmp/x", format="docx", file_size=1, content_type="doc"))
            db.add(ResumeIR(run_id=run.run_id, content="员工 简历原文 IR", valid_chars=5))
            await db.commit()
            run_id = run.run_id

        r_run = await c.get(f"/api/v1/resume-runs/{run_id}", headers=member_headers)
        assert r_run.status_code == 404
        r_ir = await c.get(f"/api/v1/resume-runs/{run_id}/ir", headers=member_headers)
        assert r_ir.status_code == 404
        r_retry = await c.post(f"/api/v1/resume-runs/{run_id}/retry", headers=member_headers)
        assert r_retry.status_code == 404


@pytest.mark.asyncio
async def test_owner_can_read_encrypted_ir(monkeypatch):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateStatus,
        ParseRun,
        ParseRunStatus,
        ResumeFile,
        ResumeIR,
    )
    from app.services.resume.ir_storage import encrypt_resume_ir

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "ir-owner@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "ir-owner@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IR-WS"}, headers=h)).json()["id"]

        async with SessionLocal() as db:
            candidate = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="候选人",
                                  structured_data={}, search_text="")
            db.add(candidate)
            await db.flush()
            run = ParseRun(run_id="ir-run-1", workspace_id=ws_id, upload_id="ir-up",
                           source_channel="job_site", format="docx", file_hash="h" * 64,
                           file_path="/tmp/x", file_size=1, parser_version="0.1.0",
                           status=ParseRunStatus.succeeded)
            db.add(run)
            await db.flush()
            db.add(ResumeFile(run_id=run.run_id, candidate_id=candidate.id, file_hash="h" * 64,
                              storage_key="/tmp/x", format="docx", file_size=1, content_type="doc"))
            db.add(ResumeIR(run_id=run.run_id, content=None, content_enc=encrypt_resume_ir("完整 IR"),
                            valid_chars=5))
            await db.commit()
            run_id = run.run_id

        r = await c.get(f"/api/v1/resume-runs/{run_id}/ir", headers=h)
        assert r.status_code == 200
        assert r.json()["content"] == "完整 IR"


@pytest.mark.asyncio
async def test_ir_route_returns_500_on_corrupted_ciphertext(monkeypatch, caplog):
    monkeypatch.setattr("app.api.resumes.parse_resume.delay", lambda run_id: None)
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateStatus,
        ParseRun,
        ParseRunStatus,
        ResumeFile,
        ResumeIR,
    )
    from app.services.resume.ir_storage import encrypt_resume_ir

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "ir-bad@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "ir-bad@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IR-BAD-WS"}, headers=h)).json()["id"]

        ciphertext = encrypt_resume_ir("完整 IR")
        corrupted = ("0" if ciphertext[0] != "0" else "1") + ciphertext[1:]
        async with SessionLocal() as db:
            candidate = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="候选人",
                                  structured_data={}, search_text="")
            db.add(candidate)
            await db.flush()
            run = ParseRun(run_id="ir-bad-run-1", workspace_id=ws_id, upload_id="ir-bad-up",
                           source_channel="job_site", format="docx", file_hash="h" * 64,
                           file_path="/tmp/x", file_size=1, parser_version="0.1.0",
                           status=ParseRunStatus.succeeded)
            db.add(run)
            await db.flush()
            db.add(ResumeFile(run_id=run.run_id, candidate_id=candidate.id, file_hash="h" * 64,
                              storage_key="/tmp/x", format="docx", file_size=1, content_type="doc"))
            db.add(ResumeIR(run_id=run.run_id, content=None, content_enc=corrupted, valid_chars=5))
            await db.commit()
            run_id = run.run_id

        r = await c.get(f"/api/v1/resume-runs/{run_id}/ir", headers=h)
        assert r.status_code == 500
        assert r.json()["message"] == "IR 内容不可读取"
        assert corrupted not in r.text
        assert "InvalidTag" not in r.text

        records = [rec for rec in caplog.records if rec.name == "app.api.resumes"]
        assert any(rec.getMessage() == "IR 解密失败" and rec.run_id == run_id for rec in records)


@pytest.mark.asyncio
async def test_content_idempotency_unique_index(monkeypatch):
    """B-6：同 (workspace, file_hash, template_version, source_channel) 只允许一条非失败 run。"""
    from sqlalchemy.exc import IntegrityError

    from app.core.database import SessionLocal
    from app.models import ParseRun, ParseRunStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="uq-owner@b.com", hashed_password="x", nickname="U")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="UQ-WS", owner_id=owner.id)
        db.add(ws)
        await db.commit()
        common = {"workspace_id": ws.id, "source_channel": "job_site", "template_version": None,
                      "file_hash": "deadbeef" * 8, "file_path": "/tmp/x", "file_size": 1,
                      "parser_version": "0.1.0"}
        db.add(ParseRun(run_id="uq-run-1", upload_id="uq-up", format="docx",
                        status=ParseRunStatus.succeeded, **common))
        await db.flush()
        db.add(ParseRun(run_id="uq-run-2", upload_id="uq-up2", format="docx",
                        status=ParseRunStatus.pending, **common))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
        # retry 复制同 hash 但原 run failed → partial 索引不拦截
        db.add(ParseRun(run_id="uq-run-1", upload_id="uq-up", format="docx",
                        status=ParseRunStatus.failed, **common))
        db.add(ParseRun(run_id="uq-run-3", upload_id="uq-up3", format="docx",
                        status=ParseRunStatus.pending, **common))
        await db.commit()