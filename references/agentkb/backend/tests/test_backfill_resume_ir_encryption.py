import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import ResumeIR
from app.services.resume.ir_storage import decrypt_resume_ir
from scripts.backfill_resume_ir_encryption import backfill_resume_irs


@pytest.mark.asyncio
async def test_backfill_encrypts_legacy_plaintext_and_is_idempotent():
    run_id = f"legacy-ir-{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        pending = (
            select(func.count())
            .select_from(ResumeIR)
            .where(ResumeIR.content_enc.is_(None), ResumeIR.content.is_not(None))
        )
        pre_count = (await db.execute(pending)).scalar_one()
        db.add(ResumeIR(run_id=run_id, content="历史原文", content_enc=None, valid_chars=4))
        await db.commit()

    migrated = await backfill_resume_irs(batch_size=1)
    assert migrated >= 1
    assert migrated == pre_count + 1

    async with SessionLocal() as db:
        refreshed = await db.get(ResumeIR, run_id)
        assert refreshed.content == "历史原文"
        assert refreshed.content_enc
        assert decrypt_resume_ir(refreshed) == "历史原文"

    assert await backfill_resume_irs(batch_size=1) == 0