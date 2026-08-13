import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    AuditEvent,
    Candidate,
    CandidateEmbedding,
    CandidateOverride,
    CandidateRevision,
    CandidateStatus,
    EmbeddingSegment,
    OverrideAction,
    ParseRun,
    ParseRunStatus,
    PIIMapping,
    PIIType,
    ResumeFile,
    ResumeIR,
)
from app.models.base import Base


@pytest.mark.asyncio
async def test_parse_run_roundtrip():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession)
    async with Session() as s:
        run = ParseRun(run_id="run-1", workspace_id=1, upload_id="up-1",
                       source_channel="referral", format="docx",
                       file_hash="abc", file_path="/tmp/x.docx", file_size=100,
                       parser_version="0.1.0", status=ParseRunStatus.pending)
        s.add(run)
        await s.commit()
        got = (await s.execute(select(ParseRun).where(ParseRun.run_id == "run-1"))).scalar_one()
        assert got.status == ParseRunStatus.pending
    await engine.dispose()

@pytest.mark.asyncio
async def test_candidate_and_revision_roundtrip():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession)
    async with Session() as s:
        c = Candidate(workspace_id=1, status=CandidateStatus.active,
                      name="张三", phone_hash="h1", email_hash="h2")
        s.add(c)
        await s.flush()
        s.add(CandidateRevision(candidate_id=c.id, run_id="run-1", revision_id="rev-1",
                                candidate_json={"name": "张三"}, evidence={}))
        s.add(CandidateOverride(candidate_id=c.id, revision_id="rev-1",
                                field_path="name", action=OverrideAction.clear, actor_id=1))
        s.add(ResumeFile(run_id="run-1", candidate_id=c.id, file_hash="abc",
                         storage_key="/tmp/x.docx", format="docx", file_size=100,
                         content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        s.add(ResumeIR(run_id="run-1", content="# 张三", valid_chars=3))
        # SQLite variant 下 embedding 列为 Text，绑定 str；PG 下 Vector 列由流水线绑定 list
        s.add(CandidateEmbedding(candidate_id=c.id, revision_id="rev-1",
                                 segment=EmbeddingSegment.work, text="支付系统", embedding="[0.1,0.2]"))
        s.add(PIIMapping(run_id="run-1", pii_type=PIIType.phone, content_hash="ch", token_enc="tok"))
        a = AuditEvent(event_id="evt-1", action="parse.run.start", result="success",
                       resource_type="parse_run")
        s.add(a)
        await s.commit()
        assert (await s.execute(select(Candidate).where(Candidate.name == "张三"))).scalar_one().status == CandidateStatus.active
        assert (await s.execute(select(AuditEvent).where(AuditEvent.event_id == "evt-1"))).scalar_one().action == "parse.run.start"
    await engine.dispose()

@pytest.mark.asyncio
async def test_conversation_supports_search_session():
    from app.core.database import SessionLocal
    from app.models import Conversation, User, Workspace

    async with SessionLocal() as db:
        owner = User(email="conv-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="conv-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        conv = Conversation(user_id=owner.id, title="搜人会话", workspace_id=ws.id, knowledge_base_id=None)
        db.add(conv)
        await db.commit()
        got = await db.get(Conversation, conv.id)
        assert got.workspace_id == ws.id and got.knowledge_base_id is None
