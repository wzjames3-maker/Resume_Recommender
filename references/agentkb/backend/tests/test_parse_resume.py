import pytest

from app.services.resume.safety import ParseSafetyError
from app.services.resume.structured import FailureClass, classify_failure


def test_safety_error_is_not_retryable():
    assert classify_failure(ParseSafetyError("加密")) is FailureClass.not_retryable


def test_llm_timeout_is_retryable():
    assert classify_failure(TimeoutError()) is FailureClass.retryable


def test_pipeline_marks_short_ir_failed():
    # 不依赖 DB 的最小验证：IR 低于阈值直接 failed
    from app.services.resume.ir import IR_VALID_CHARS_THRESHOLD, validate_ir
    with pytest.raises(ValueError, match="有效字符"):
        validate_ir("短" * (IR_VALID_CHARS_THRESHOLD - 1))


@pytest.mark.asyncio
async def test_redis_lease_skips_duplicate_delivery(monkeypatch):
    from app.tasks import parse_resume as task_module

    class FakeRedis:
        async def set(self, *args, **kwargs):
            return False
        async def aclose(self):
            pass

    monkeypatch.setattr(task_module.Redis, "from_url", lambda *args, **kwargs: FakeRedis())
    client, should_execute = await task_module._acquire_lease("run-1")
    assert client is None and should_execute is False


@pytest.mark.asyncio
async def test_parse_checkpoint_roundtrip():
    from app.core.database import SessionLocal
    from app.services.resume.pii import PIIMappingEntry, PIIType
    from app.services.resume.pipeline import _load_checkpoint, _save_checkpoint
    from app.services.resume.structured import StructuredResult

    structured = StructuredResult(
        candidate={"name": "张三", "phone": "13800000000", "work": []},
        evidence={"name": {"block_id": 1, "quote_hash": "abc123"}},
        pii_mapping=[PIIMappingEntry(PIIType.phone, "13800000000", "PII:phone:0")],
    )
    profile = {"values": {"level": None}, "evidence": {}}
    async with SessionLocal() as db:
        await _save_checkpoint(db, "cp-run-1", structured, profile)
        await db.commit()
    async with SessionLocal() as db:
        loaded = await _load_checkpoint(db, "cp-run-1")
        assert loaded is not None
        s2, p2 = loaded
        assert s2.candidate["name"] == "张三"
        assert s2.candidate["phone"] == "13800000000"
        assert s2.pii_mapping[0].value == "13800000000"
        assert s2.evidence["name"]["quote_hash"] == "abc123"
        assert p2 == profile


@pytest.mark.asyncio
async def test_pipeline_reuses_llm_checkpoint_on_retry(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import ParseRun, ParseRunStatus, User, Workspace
    from app.services.resume.pipeline import run_pipeline

    calls = {"llm": 0, "embed": 0}

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            calls["llm"] += 1
            if "画像分析师" in system:
                return {"profile": {"level": None}, "evidence": {}}
            return {"candidate": {"name": "张三", "skills": ["Java"], "work": [], "project": [], "education": []},
                    "evidence": {}}

    class FakeEmbedder:
        def __init__(self):
            self.fail_first = True

        async def embed(self, texts):
            calls["embed"] += 1
            if self.fail_first:
                self.fail_first = False
                raise TimeoutError("embedding timeout")
            return [[0.1] * 1024 for _ in texts]

    embedder = FakeEmbedder()

    async def fake_get_llm(db, ws):
        return FakeLLM(), SimpleNamespace(base_url="https://api.deepseek.com/v1", model_name="deepseek-chat")

    async def fake_get_embedder(db, ws):
        return embedder

    monkeypatch.setattr("app.services.resume.pipeline._get_llm", fake_get_llm)
    monkeypatch.setattr("app.services.resume.pipeline._get_embedder", fake_get_embedder)

    path = tmp_path / "resume.txt"
    path.write_text("姓名：张三\n" + "工作经历 " * 60, encoding="utf-8")

    async with SessionLocal() as db:
        owner = User(email="chk-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="chk-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        run = ParseRun(run_id="chk-run-1", workspace_id=ws.id, upload_id="up", source_channel="job_site",
                       format="txt", file_hash="h", file_path=str(path), file_size=100,
                       parser_version="0.1.0", status=ParseRunStatus.pending, template_version=None)
        db.add(run)
        await db.commit()

    # 第一次：LLM 后 embedding 失败 → 检查点已写、LLM 已调用
    async with SessionLocal() as db:
        run = (await db.execute(select(ParseRun).where(ParseRun.run_id == "chk-run-1"))).scalar_one()
        with pytest.raises(TimeoutError):
            await run_pipeline(db, run, path.read_bytes())
    assert calls["llm"] == 2  # extract + profile

    # 第二次：复用检查点，不再调用 LLM，仅重跑 embedding 与入库
    async with SessionLocal() as db:
        run = (await db.execute(select(ParseRun).where(ParseRun.run_id == "chk-run-1"))).scalar_one()
        outcome = await run_pipeline(db, run, path.read_bytes())
        assert outcome.status is ParseRunStatus.succeeded
    assert calls["llm"] == 2
    assert calls["embed"] == 2


_SAMPLE_CANDIDATE = {
    "name": "张三",
    "phone": "13800000000",
    "email": "zhangsan@example.com",
    "city": "杭州",
    "skills": ["Java"],
    "work": [{"company": "A公司", "title": "后端工程师",
              "content": "负责支付系统\n现住址：浙江省杭州市西湖区文三路 90 号\n电话：13800000000",
              "start": "2017-07", "end": "2021-06"}],
    "education": [],
    "project": [],
}


# 任务 5：画像调用点出站脱敏（A-15）。姓名/电话/邮箱字段由 _PII_OUTBOUND_FIELDS 过滤；
# 本测试把地址与电话明文放入 work content 自由文本，只有 desensitize_text 能将其替换为
# PII token，从而锁定画像出站脱敏而非仅字段过滤。
@pytest.mark.asyncio
async def test_profile_masks_pii_before_outbound():
    from app.services.resume.profile import generate_profile

    captured: dict[str, str] = {}

    class FakeLLM:
        async def chat_json(self, system, user, schema):
            captured["user"] = user
            return {"profile": {"level": None}, "evidence": {}}

    await generate_profile(FakeLLM(), _SAMPLE_CANDIDATE, {})

    user = captured["user"]
    assert "张三" not in user
    assert "13800000000" not in user
    assert "zhangsan@example.com" not in user
    assert "浙江省杭州市西湖区文三路 90 号" not in user
    assert "PII:address:" in user
    assert "PII:phone:" in user


@pytest.mark.asyncio
async def test_mark_terminal_does_not_overwrite_succeeded():
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import ParseRun, ParseRunStatus, User, Workspace
    from app.tasks.parse_resume import _mark_terminal

    async with SessionLocal() as db:
        owner = User(email="mt-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="mt-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        run = ParseRun(run_id="mt-run", workspace_id=ws.id, upload_id="u", source_channel="job_site",
                       format="txt", file_hash="h", file_path="/tmp/x", file_size=1,
                       parser_version="0.1.0", status=ParseRunStatus.succeeded)
        db.add(run)
        await db.commit()
        await _mark_terminal("mt-run", ValueError("boom"), retryable=False)
    async with SessionLocal() as db:
        run = (await db.execute(select(ParseRun).where(ParseRun.run_id == "mt-run"))).scalar_one()
        assert run.status is ParseRunStatus.succeeded
        assert run.error_message is None
