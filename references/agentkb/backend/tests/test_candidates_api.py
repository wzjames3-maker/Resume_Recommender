import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

_seed_seq = 0


async def _seed_candidate(ws_id: int, *, name: str = "张三", status: str = "active"):
    global _seed_seq
    _seed_seq += 1
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateRevision, CandidateStatus

    async with SessionLocal() as db:
        cand = Candidate(workspace_id=ws_id, status=CandidateStatus(status), name=name,
                         structured_data={"city": "杭州", "skills": ["Java"]}, search_text="Java")
        db.add(cand)
        await db.flush()
        rid = f"cd-r{_seed_seq}"
        rev = CandidateRevision(candidate_id=cand.id, run_id=rid, revision_id=f"{rid}:rev1",
                                candidate_json={"name": name, "city": "杭州", "skills": ["Java"]},
                                evidence={}, profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        await db.commit()
        return cand.id


@pytest.mark.asyncio
async def test_get_candidate_detail_returns_effective_fields():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "cd@b.com", "password": "secret123", "nickname": "C"})
        token = (await c.post("/api/v1/auth/login", json={"email": "cd@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "CD-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)
        r = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["candidate"]["fields"]["city"] == "杭州"
        assert body["candidate"]["fields"]["skills"] == ["Java"]
        assert body["candidate"]["profile"]["level"] == "Mid"


@pytest.mark.asyncio
async def test_candidate_cross_workspace_isolated():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "cd2@b.com", "password": "secret123", "nickname": "C2"})
        token = (await c.post("/api/v1/auth/login", json={"email": "cd2@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_a = (await c.post("/api/v1/workspaces", json={"name": "A"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_a)
        ws_b = (await c.post("/api/v1/workspaces", json={"name": "B"}, headers=h)).json()["id"]
        r = await c.get(f"/api/v1/workspaces/{ws_b}/candidates/{cand_id}", headers=h)
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_owner_can_view_hired():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "cd3@b.com", "password": "secret123", "nickname": "C3"})
        token = (await c.post("/api/v1/auth/login", json={"email": "cd3@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "H"}, headers=h)).json()["id"]
        hired_id = await _seed_candidate(ws_id, name="李四", status="hired")
        r = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{hired_id}", headers=h)
        assert r.status_code == 200
        assert r.json()["candidate"]["status"] == "hired"


@pytest.mark.asyncio
async def test_candidate_detail_decrypts_ir():
    from app.core.database import SessionLocal
    from app.models import ParseRun, ResumeFile, ResumeIR
    from app.services.resume.ir_storage import encrypt_resume_ir

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "ir-cd@b.com", "password": "secret123", "nickname": "C"})
        token = (await c.post("/api/v1/auth/login", json={"email": "ir-cd@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IRCD-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)

        async with SessionLocal() as db:
            run = ParseRun(run_id=f"ir-cd-run-{cand_id}", workspace_id=ws_id, upload_id="ir-cd-up",
                           source_channel="job_site", format="docx", file_hash="h" * 64,
                           file_path="/tmp/x", file_size=1, parser_version="0.1.0")
            db.add(run)
            await db.flush()
            db.add(ResumeFile(run_id=run.run_id, candidate_id=cand_id, file_hash="h" * 64,
                              storage_key="/tmp/x", format="docx", file_size=1, content_type="doc"))
            db.add(ResumeIR(run_id=run.run_id, content=None, content_enc=encrypt_resume_ir("候选人 IR 原文"),
                            valid_chars=5))
            await db.commit()

        r = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        assert r.status_code == 200
        assert r.json()["ir"] == "候选人 IR 原文"


@pytest.mark.asyncio
async def test_candidate_detail_returns_500_on_corrupted_ir_ciphertext(caplog):
    from app.core.database import SessionLocal
    from app.models import ParseRun, ResumeFile, ResumeIR
    from app.services.resume.ir_storage import encrypt_resume_ir

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "ir-badcd@b.com", "password": "secret123", "nickname": "C"})
        token = (await c.post("/api/v1/auth/login", json={"email": "ir-badcd@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IRBADCD-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)

        ciphertext = encrypt_resume_ir("候选人 IR 原文")
        corrupted = ciphertext[:-1] + ("0" if ciphertext[-1] != "0" else "1")
        async with SessionLocal() as db:
            run = ParseRun(run_id=f"ir-badcd-run-{cand_id}", workspace_id=ws_id, upload_id="ir-badcd-up",
                           source_channel="job_site", format="docx", file_hash="h" * 64,
                           file_path="/tmp/x", file_size=1, parser_version="0.1.0")
            db.add(run)
            await db.flush()
            db.add(ResumeFile(run_id=run.run_id, candidate_id=cand_id, file_hash="h" * 64,
                              storage_key="/tmp/x", format="docx", file_size=1, content_type="doc"))
            db.add(ResumeIR(run_id=run.run_id, content=None, content_enc=corrupted, valid_chars=5))
            await db.commit()

        r = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        assert r.status_code == 500
        assert r.json()["message"] == "IR 内容不可读取"
        assert corrupted not in r.text
        assert "InvalidTag" not in r.text

        records = [rec for rec in caplog.records if rec.name == "app.api.candidates"]
        assert any(rec.getMessage() == "IR 解密失败" and rec.run_id == f"ir-badcd-run-{cand_id}"
                   for rec in records)


@pytest.mark.asyncio
async def test_override_field_records_event_and_conflict():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "ov@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "ov@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "OV-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)
        # 获取 latest_revision_id
        detail = (await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)).json()
        rev_id = detail["candidate"]["latest_revision_id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/fields",
                         json={"base_revision_id": rev_id, "field_path": "city",
                               "action": "override", "after_value": "上海"}, headers=h)
        assert r.status_code == 200
        assert r.json()["fields"]["city"] == "上海"
        # 并发冲突：base_revision_id 过期
        r2 = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/fields",
                          json={"base_revision_id": 999, "field_path": "city",
                                "action": "override", "after_value": "北京"}, headers=h)
        assert r2.status_code == 409
        # clear
        r3 = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/fields",
                          json={"base_revision_id": rev_id, "field_path": "city",
                                "action": "clear", "after_value": None}, headers=h)
        assert r3.status_code == 200
        assert r3.json()["fields"]["city"] is None


@pytest.mark.asyncio
async def test_candidate_soft_delete_restore_and_purge():
    from app.core.database import SessionLocal

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "lc@b.com", "password": "secret123", "nickname": "L"})
        token = (await c.post("/api/v1/auth/login", json={"email": "lc@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "LC-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)
        # 软删除
        r = await c.delete(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"
        # 恢复
        r2 = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/restore", headers=h)
        assert r2.status_code == 200
        assert r2.json()["status"] == "active"
        # 再删再 purge：30 天保留期内拒绝
        await c.delete(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        r_purge_blocked = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/purge", headers=h)
        assert r_purge_blocked.status_code == 409
        # 保留期结束（deleted_until 已过期）后可 purge
        async with SessionLocal() as db:
            from datetime import UTC, datetime, timedelta

            from app.models import Candidate

            cand = await db.get(Candidate, cand_id)
            cand.deleted_until = datetime.now(UTC) - timedelta(days=1)
            await db.commit()
        r3 = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/purge", headers=h)
        assert r3.status_code == 200
        assert r3.json()["status"] == "purged"
        # 已硬删 → 详情 404
        assert (await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_hired_candidate_cannot_be_deleted():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "hd@b.com", "password": "secret123", "nickname": "H"})
        token = (await c.post("/api/v1/auth/login", json={"email": "hd@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "HD-WS"}, headers=h)).json()["id"]
        hired_id = await _seed_candidate(ws_id, name="李四", status="hired")
        r = await c.delete(f"/api/v1/workspaces/{ws_id}/candidates/{hired_id}", headers=h)
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_candidate_with_active_assignment_cannot_be_deleted():
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import Assignment, AssignmentStatus, Job, User

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "ad-owner@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "ad-owner@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "AD-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)
        async with SessionLocal() as db:
            owner_id = (await db.execute(select(User.id).where(User.email == "ad-owner@b.com"))).scalar_one()
            job = Job(workspace_id=ws_id, name="后端", description="", headcount=2)
            db.add(job)
            await db.flush()
            db.add(Assignment(workspace_id=ws_id, candidate_id=cand_id, job_id=job.id,
                              status=AssignmentStatus.pending_screen, created_by=owner_id))
            await db.commit()
        r = await c.delete(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        assert r.status_code == 409
        assert "进行中指派" in r.json()["message"]


@pytest.mark.asyncio
async def test_restore_recomputes_pool_from_assignments():
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import (
        Assignment,
        AssignmentStatus,
        Candidate,
        CandidateStatus,
        Job,
        User,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "rp-owner@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "rp-owner@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "RP-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)
        async with SessionLocal() as db:
            owner_id = (await db.execute(select(User.id).where(User.email == "rp-owner@b.com"))).scalar_one()
            job = Job(workspace_id=ws_id, name="前端", description="", headcount=2)
            db.add(job)
            await db.flush()
            db.add(Assignment(workspace_id=ws_id, candidate_id=cand_id, job_id=job.id,
                              status=AssignmentStatus.offer_rejected, created_by=owner_id))
            await db.commit()
        await c.delete(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/restore", headers=h)
        assert r.status_code == 200
        async with SessionLocal() as db:
            cand = await db.get(Candidate, cand_id)
            assert cand.status is CandidateStatus.rejected  # 恢复后按指派终态重算


@pytest.mark.asyncio
async def test_purge_removes_physical_files():
    import os

    from app.core.database import SessionLocal
    from app.models import Candidate, ResumeFile

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "pf-owner@b.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "pf-owner@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "PF-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)
        storage_path = "/tmp/opencode/pf-test-file.docx"
        with open(storage_path, "wb") as fh:  # noqa: ASYNC230
            fh.write(b"resume content")
        async with SessionLocal() as db:
            from datetime import UTC, datetime, timedelta

            cand = await db.get(Candidate, cand_id)
            cand.deleted_until = datetime.now(UTC) + timedelta(days=30)
            db.add(ResumeFile(run_id=f"pf-run-{cand_id}", candidate_id=cand_id, file_hash="f" * 64,
                              storage_key=storage_path, format="docx", file_size=14, content_type="doc"))
            await db.commit()
        await c.delete(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        async with SessionLocal() as db:
            from datetime import UTC, datetime, timedelta

            cand = await db.get(Candidate, cand_id)
            cand.deleted_until = datetime.now(UTC) - timedelta(days=1)
            await db.commit()
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/purge", headers=h)
        assert r.status_code == 200
        assert not os.path.exists(storage_path)


@pytest.mark.asyncio
async def test_candidate_timeline_and_note():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "tl@b.com", "password": "secret123", "nickname": "T"})
        token = (await c.post("/api/v1/auth/login", json={"email": "tl@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "TL-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)
        r_note = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/notes",
                              json={"content": "初面通过"}, headers=h)
        assert r_note.status_code == 200
        r_tl = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/timeline", headers=h)
        assert r_tl.status_code == 200
        assert any("初面通过" in e["title"] for e in r_tl.json()["items"])


@pytest.mark.asyncio
async def test_list_candidates_api_filters_and_include_deleted():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "li@b.com", "password": "secret123", "nickname": "L"})
        token = (await c.post("/api/v1/auth/login", json={"email": "li@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "LI-WS"}, headers=h)).json()["id"]
        active_id = await _seed_candidate(ws_id, name="张三")
        await _seed_candidate(ws_id, name="李四", status="hired")
        # owner 可见 hired
        r = await c.get(f"/api/v1/workspaces/{ws_id}/candidates", headers=h)
        names = {i["name"] for i in r.json()["items"]}
        assert "张三" in names and "李四" in names
        # 软删后默认列表不含
        await c.delete(f"/api/v1/workspaces/{ws_id}/candidates/{active_id}", headers=h)
        r2 = await c.get(f"/api/v1/workspaces/{ws_id}/candidates", headers=h)
        assert not any(i["candidate_id"] == active_id for i in r2.json()["items"])
        # include_deleted 含已删
        r3 = await c.get(f"/api/v1/workspaces/{ws_id}/candidates", params={"include_deleted": "true"}, headers=h)
        assert any(i["candidate_id"] == active_id for i in r3.json()["items"])


@pytest.mark.asyncio
async def test_override_invalid_field_path_not_silently_lost():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "iv@b.com", "password": "secret123", "nickname": "I"})
        token = (await c.post("/api/v1/auth/login", json={"email": "iv@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "IV-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)
        detail = (await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)).json()
        rev_id = detail["candidate"]["latest_revision_id"]
        # 未知顶层字段 → 拒绝（不静默写入）
        r0 = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/fields",
                          json={"base_revision_id": rev_id, "field_path": "fabricated_field",
                                "action": "override", "after_value": "x"}, headers=h)
        assert r0.status_code == 400
        # 标量字段嵌套子路径 → 拒绝
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/fields",
                         json={"base_revision_id": rev_id, "field_path": "name.sub",
                               "action": "override", "after_value": "x"}, headers=h)
        assert r.status_code == 400
        assert "标量字段" in r.json()["message"]
        # 数组字段合法子路径 → 允许
        r2 = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/fields",
                          json={"base_revision_id": rev_id, "field_path": "work[0].title",
                                "action": "override", "after_value": "工程师"}, headers=h)
        assert r2.status_code == 200
        assert r2.json()["fields"]["work"][0]["title"] == "工程师"


@pytest.mark.asyncio
async def test_override_pii_goes_to_encrypted_column():
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateOverride

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "pe@b.com", "password": "secret123", "nickname": "P"})
        token = (await c.post("/api/v1/auth/login", json={"email": "pe@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "PE-WS"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_id)
        detail = (await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)).json()
        rev_id = detail["candidate"]["latest_revision_id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}/fields",
                         json={"base_revision_id": rev_id, "field_path": "phone",
                               "action": "override", "after_value": "13900000000"}, headers=h)
        assert r.status_code == 200
        async with SessionLocal() as db:
            cand = await db.get(Candidate, cand_id)
            assert cand.phone_enc and cand.phone_enc != "13900000000"
            assert cand.phone_hash
            overrides = (await db.execute(select(CandidateOverride).where(
                CandidateOverride.candidate_id == cand_id))).scalars().all()
            assert all(o.field_path != "phone" for o in overrides)  # PII 不进 JSON override


@pytest.mark.asyncio
async def test_restore_purge_cross_workspace_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "rp@b.com", "password": "secret123", "nickname": "R"})
        token = (await c.post("/api/v1/auth/login", json={"email": "rp@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_a = (await c.post("/api/v1/workspaces", json={"name": "RPA"}, headers=h)).json()["id"]
        cand_id = await _seed_candidate(ws_a)
        await c.delete(f"/api/v1/workspaces/{ws_a}/candidates/{cand_id}", headers=h)
        ws_b = (await c.post("/api/v1/workspaces", json={"name": "RPB"}, headers=h)).json()["id"]
        assert (await c.post(f"/api/v1/workspaces/{ws_b}/candidates/{cand_id}/restore", headers=h)).status_code == 404
        assert (await c.post(f"/api/v1/workspaces/{ws_b}/candidates/{cand_id}/purge", headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_candidate_detail_includes_suitable_jobs():
    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateRevision,
        CandidateStatus,
        Job,
        JobRequirementRevision,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "sj-owner@example.com", "password": "secret123", "nickname": "S"})
        token = (await c.post("/api/v1/auth/login", json={"email": "sj-owner@example.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "SJ-WS"}, headers=h)).json()["id"]

    async with SessionLocal() as db:
        cand = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                         structured_data={"skills": ["Vue"], "city": "杭州"}, search_text="Vue")
        db.add(cand)
        await db.flush()
        rev = CandidateRevision(candidate_id=cand.id, run_id="sj-r", revision_id="sj-r:rev1",
                                candidate_json={"skills": ["Vue"], "city": "杭州"}, evidence={},
                                profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev)
        await db.flush()
        cand.latest_revision_id = rev.id
        cand_id = cand.id
        job = Job(workspace_id=ws_id, name="前端开发工程师", description="精通 Vue", headcount=1)
        db.add(job)
        await db.flush()
        jr = JobRequirementRevision(job_id=job.id, revision=1, description=job.description,
                                    parsed_ast=[{"field": "skills", "op": "contains", "value": ["Vue"],
                                                 "logic": "AND", "missing_policy": "exclude"}],
                                    schema_version="search/v1", prompt_version="job-req-prompt/v1",
                                    evidence={"skills": {"locator": "精通 Vue"}})
        db.add(jr)
        await db.flush()
        job.latest_revision_id = jr.id
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = (await c.post("/api/v1/auth/login", json={"email": "sj-owner@example.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{cand_id}", headers=h)
        assert r.status_code == 200
        jobs = r.json()["suitable_jobs"]
        assert jobs and jobs[0]["name"] == "前端开发工程师"
        assert jobs[0]["matched_conditions"] == ["skills"]


@pytest.mark.asyncio
async def test_merge_candidates_api_and_referrer_detail():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, ParseRun, ResumeFile

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "mrg-owner@example.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "mrg-owner@example.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "MRG-WS"}, headers=h)).json()["id"]

    async with SessionLocal() as db:
        from app.models import CandidateRevision
        primary = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                            structured_data={"city": "杭州"}, search_text="杭州")
        absorbed = Candidate(workspace_id=ws_id, status=CandidateStatus.pending_review, name="张三",
                             structured_data={"skills": ["Java"]}, search_text="Java")
        db.add_all([primary, absorbed])
        await db.flush()
        rp = CandidateRevision(candidate_id=primary.id, run_id="mrg-p", revision_id="mrg-p:rev1",
                               candidate_json={"name": "张三", "city": "杭州"}, evidence={})
        db.add(rp)
        await db.flush()
        primary.latest_revision_id = rp.id
        ra = CandidateRevision(candidate_id=absorbed.id, run_id="mrg-a", revision_id="mrg-a:rev1",
                               candidate_json={"name": "张三", "skills": ["Java"]}, evidence={})
        db.add(ra)
        await db.flush()
        absorbed.latest_revision_id = ra.id
        base = primary.latest_revision_id
        run = ParseRun(run_id="mrg-run", workspace_id=ws_id, upload_id="u1", source_channel="referral",
                       referrer="李四", format="pdf", file_hash="f1", file_path="p1", file_size=1,
                       parser_version="v1")
        db.add(run)
        await db.flush()
        db.add(ResumeFile(run_id="mrg-run", candidate_id=primary.id, file_hash="f1", storage_key="k1",
                          format="pdf", file_size=1, content_type="application/pdf"))
        await db.commit()
        p_id, a_id = primary.id, absorbed.id

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = (await c.post("/api/v1/auth/login", json={"email": "mrg-owner@example.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{p_id}", headers=h)
        assert r.status_code == 200
        assert r.json()["source_channel"] == "referral"
        assert r.json()["referrer"] == "李四"
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{p_id}/merge", headers=h,
                         json={"duplicate_id": a_id, "base_revision_id": base})
        assert r.status_code == 200
        assert r.json()["status"] == "merged"
        assert (await c.get(f"/api/v1/workspaces/{ws_id}/candidates/{a_id}", headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_merge_conflict_api_409():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "mrg2-owner@example.com", "password": "secret123", "nickname": "O"})
        token = (await c.post("/api/v1/auth/login", json={"email": "mrg2-owner@example.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws_id = (await c.post("/api/v1/workspaces", json={"name": "MRG2-WS"}, headers=h)).json()["id"]

    async with SessionLocal() as db:
        primary = Candidate(workspace_id=ws_id, status=CandidateStatus.active, name="张三",
                            structured_data={}, search_text="")
        absorbed = Candidate(workspace_id=ws_id, status=CandidateStatus.pending_review, name="张三",
                             structured_data={}, search_text="")
        db.add_all([primary, absorbed])
        await db.commit()
        p_id, a_id = primary.id, absorbed.id

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = (await c.post("/api/v1/auth/login", json={"email": "mrg2-owner@example.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(f"/api/v1/workspaces/{ws_id}/candidates/{p_id}/merge", headers=h,
                         json={"duplicate_id": a_id, "base_revision_id": 999})
        assert r.status_code == 409
