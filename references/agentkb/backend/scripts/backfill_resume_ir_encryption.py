import argparse
import asyncio

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import ResumeIR
from app.services.resume.ir_storage import encrypt_resume_ir


async def backfill_resume_irs(batch_size: int = 500) -> int:
    migrated = 0
    while True:
        async with SessionLocal() as db:
            stmt = select(ResumeIR).where(
                ResumeIR.content_enc.is_(None), ResumeIR.content.is_not(None)
            ).order_by(ResumeIR.run_id).limit(batch_size)
            rows = (await db.execute(stmt)).scalars().all()
            if not rows:
                return migrated
            for ir in rows:
                ir.content_enc = encrypt_resume_ir(ir.content)
            migrated += len(rows)
            await db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    print(asyncio.run(backfill_resume_irs(args.batch_size)))


if __name__ == "__main__":
    main()