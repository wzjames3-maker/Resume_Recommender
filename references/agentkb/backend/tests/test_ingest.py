import pytest
from sqlalchemy import select

from app.services.resume.dedup import (
    hash_identity,
    normalize_email,
    normalize_phone,
    normalize_skills,
)
from app.services.resume.ingest import search_duplicates
from app.services.resume.segments import build_search_text, build_segments


def test_normalize_skills_dedupes_and_trims():
    assert normalize_skills([" Java ", "Java", "  Python ", "Java"]) == ["Java", "Python"]
    assert normalize_skills(None) is None
    assert normalize_skills([]) == []


def test_normalize_phone():
    assert normalize_phone("+86 138 0000 0000") == "13800000000"
    assert normalize_phone("１３８００００００００") == "13800000000"  # 全角


def test_normalize_email():
    assert normalize_email("  Zhangsan@Example.COM ") == "zhangsan@example.com"


def test_hash_identity_consistent():
    assert hash_identity(normalize_phone("13800000000")) == hash_identity("13800000000")


def test_build_segments_all_five():
    candidate = {
        "name": "张三", "city": "杭州", "expected_position": "Java 后端",
        "skills": ["Java", "Spring"],
        "education": [{"school": "H 大学", "major": "计算机", "start": "2013-09", "end": "2017-06"}],
        "work": [{"company": "A 公司", "title": "后端工程师", "content": "负责支付系统", "start": "2017-07", "end": "2021-06"}],
        "project": [{"name": "支付平台", "responsibility": "核心开发"}],
    }
    segs = build_segments(candidate)
    assert set(segs) == {"summary", "education", "work", "project", "skills"}
    assert "支付系统" in segs["work"]
    assert "Java" in segs["skills"]
    # A-15：摘要段出站 embedding，不得含姓名/联系方式
    assert "张三" not in segs["summary"] and "138" not in segs["summary"]


def test_build_search_text_excludes_contact_pii_but_keeps_name_and_skills():
    candidate = {"name": "张三", "phone": "13800000000", "email": "a@b.com",
                 "city": "杭州", "skills": ["Java", "Spring"]}
    text = build_search_text(candidate)
    assert "13800000000" not in text and "a@b.com" not in text
    assert "张三" in text and "Java" in text  # 姓名/技能本地可检索


@pytest.mark.asyncio
async def test_search_duplicates_returns_matching_candidates():
    # 需要 DB：用 conftest 注入的 PG 库；先建 workspace 满足 FK
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="dup-owner@example.com", hashed_password="x", nickname="dup-owner")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="dup-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        db.add(Candidate(workspace_id=ws.id, status=CandidateStatus.active,
                         name="张三", phone_hash=hash_identity("13800000000"),
                         email_hash=hash_identity("zhangsan@example.com")))
        await db.commit()
        hits = await search_duplicates(db, ws.id, "张三", hash_identity("13800000000"), None)
        assert len(hits) >= 1
        assert hits[0].name == "张三"


@pytest.mark.asyncio
async def test_ingest_writes_real_vectors_pii_mapping_and_pending_review():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, PIIMapping, User, Workspace
    from app.services.resume.ingest import ingest
    from app.services.resume.pii import desensitize_text

    candidate = {"name": "王五", "phone": "13900000000", "email": "w@example.com",
                 "city": "杭州", "skills": ["Python"], "education": [], "work": [], "project": []}
    _, mappings = desensitize_text("姓名：王五 电话 13900000000 邮箱 w@example.com")
    async with SessionLocal() as db:
        owner = User(email="ingest-owner@example.com", hashed_password="x", nickname="owner")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="ingest-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        duplicate = Candidate(workspace_id=ws.id, status=CandidateStatus.active,
                              name="王五", phone_hash=hash_identity("13900000000"))
        db.add(duplicate)
        await db.flush()
        segments = build_segments(candidate)
        vectors = {name: [0.1] * 1024 for name, text in segments.items() if text.strip()}
        cand = await ingest(
            db, workspace_id=ws.id, run_id="run-ingest", revision_id="run-ingest:rev1",
            candidate=candidate, evidence={}, profile=None, ir_text="# 王五", ir_valid_chars=3,
            file_hash="f" * 64, storage_key="/tmp/record.json", fmt="json",
            content_type="application/json", file_size=1, duplicates=[duplicate],
            segments=segments, embeddings=vectors, pii_entries=mappings,
        )
        assert cand.status is CandidateStatus.pending_review
        assert cand.phone_enc and cand.phone_hash == hash_identity("13900000000")
        assert (await db.execute(select(PIIMapping).where(PIIMapping.run_id == "run-ingest"))).scalars().all()

        from app.models import ResumeIR
        from app.services.resume.ir_storage import decrypt_resume_ir

        ir = await db.get(ResumeIR, "run-ingest")
        assert ir.content is None
        assert ir.content_enc and "# 王五" not in ir.content_enc
        assert decrypt_resume_ir(ir) == "# 王五"


# 任务 5：embedding 调用点出站脱敏（A-15）。地址若落入 work content 文本，
# 必须在出站 embedding 前被 desensitize_text 替换为 token。
_SAMPLE_CANDIDATE = {
    "name": "张三",
    "phone": "13800000000",
    "email": "zhangsan@example.com",
    "city": "杭州",
    "skills": ["Java"],
    "work": [{"company": "A公司", "title": "后端工程师",
              "content": "负责支付系统",
              "start": "2017-07", "end": "2021-06"}],
    "education": [],
    "project": [],
}


@pytest.mark.asyncio
async def test_embed_segments_masks_pii_before_outbound(monkeypatch):
    from app.services.resume.pipeline import _embed_segments

    captured: dict[str, list[str]] = {"texts": []}

    class FakeEmbedder:
        async def embed(self, texts):
            captured["texts"] = list(texts)
            return [[0.1] * 1024 for _ in texts]

    async def _fake_get_embedder(db, workspace_id):
        return FakeEmbedder()

    monkeypatch.setattr("app.services.resume.pipeline._get_embedder", _fake_get_embedder)

    candidate = dict(_SAMPLE_CANDIDATE)
    candidate["work"] = [{"company": "A公司", "title": "后端工程师",
                          "content": "负责支付系统\n现住址：浙江省杭州市西湖区文三路 90 号",
                          "start": "2017-07", "end": "2021-06"}]
    _, vectors = await _embed_segments(None, 1, candidate)
    assert len(vectors) == len(captured["texts"])

    for text in captured["texts"]:
        assert "张三" not in text
        assert "13800000000" not in text
        assert "浙江省杭州市西湖区文三路 90 号" not in text
    assert any("PII:address:" in text for text in captured["texts"]), "work 段地址应被替换为 token"
