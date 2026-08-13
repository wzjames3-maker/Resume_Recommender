import asyncio
import logging
from pathlib import Path

from celery import shared_task
from redis.asyncio import Redis
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.models import FailureClass as FailureClassEnum
from app.models import ParseRun, ParseRunStatus
from app.services.audit import add_event
from app.services.resume.pipeline import run_pipeline
from app.services.resume.structured import FailureClass, classify_failure

logger = logging.getLogger(__name__)

MAX_AUTO_RETRIES = settings.resume_max_auto_retries
LEASE_SECONDS = 10 * 60


async def _acquire_lease(run_id: str) -> tuple[Redis | None, bool]:
    """A-18：Redis 为尽力互斥；不可用不阻断，DB 唯一约束仍是最终保障。"""
    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        if await client.set(f"resume:lease:{run_id}", "1", nx=True, ex=LEASE_SECONDS):
            return client, True
        await client.aclose()
        return None, False  # Redis 正常，但已有 worker 持有该 run 的 lease
    except Exception as exc:  # noqa: BLE001
        logger.warning("resume lease unavailable for %s: %s; falling back to DB idempotency", run_id, exc)
    return None, True         # Redis 不可用：继续，交给 DB 状态/唯一约束兜底


async def _release_lease(run_id: str, client: Redis | None) -> None:
    if client is None:
        return
    try:
        await client.delete(f"resume:lease:{run_id}")
    finally:
        await client.aclose()


async def _execute(run_id: str, retry_count: int) -> None:
    await engine.dispose()
    lease, should_execute = await _acquire_lease(run_id)
    if not should_execute:
        logger.info("run %s 已由其他 worker 持有 lease，跳过重复投递", run_id)
        return
    try:
        async with SessionLocal() as db:
            run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one_or_none()
            if run is None:
                return
            # 幂等：已终态不重复执行
            if run.status in (ParseRunStatus.succeeded, ParseRunStatus.failed, ParseRunStatus.dead_letter):
                logger.info("run %s 已终态 %s，跳过", run_id, run.status)
                return
            if run.status == ParseRunStatus.processing:
                # worker 重启 / 重复投递：processing 视为可安全重跑（入库幂等兜底）
                logger.warning("run %s 处于 processing，尝试重跑", run_id)
            run.retry_count = retry_count
            file_bytes = Path(run.file_path).read_bytes()
            await run_pipeline(db, run, file_bytes)
    finally:
        await _release_lease(run_id, lease)
        await engine.dispose()


@shared_task(bind=True, max_retries=MAX_AUTO_RETRIES)
def parse_resume(self, run_id: str) -> None:
    try:
        asyncio.run(_execute(run_id, self.request.retries))
    except Exception as exc:
        retryable = classify_failure(exc) is FailureClass.retryable
        if retryable and self.request.retries < MAX_AUTO_RETRIES:
            countdown = 2 ** (self.request.retries + 1)  # 指数退避
            raise self.retry(exc=exc, countdown=countdown)
        # A-14：不可重试 → failed；可重试自动重试耗尽 → dead_letter。
        asyncio.run(_mark_terminal(run_id, exc, retryable))
        raise


async def _mark_terminal(run_id: str, exc: Exception, retryable: bool) -> None:
    async with SessionLocal() as db:
        # 原子条件更新：仅当 run 仍在 pending/processing 时置为失败终态。
        # 并发重复投递中另一 worker 已提交 success 时 rowcount=0，绝不覆盖已发布成功结果，
        # 也不会产生 spurious 的 parse.run.failed 审计事件。
        result = await db.execute(
            update(ParseRun)
            .where(ParseRun.run_id == run_id,
                   ParseRun.status.in_([ParseRunStatus.pending, ParseRunStatus.processing]))
            .values(
                status=ParseRunStatus.dead_letter if retryable else ParseRunStatus.failed,
                failure_class=FailureClassEnum.retryable if retryable else FailureClassEnum.not_retryable,
                error_message=str(exc),
            )
        )
        if result.rowcount == 0:
            return
        run = (await db.execute(select(ParseRun).where(ParseRun.run_id == run_id))).scalar_one()
        await add_event(db, action=f"parse.run.{run.status.value}", result="failure",
                        resource_type="parse_run", resource_id=run.run_id,
                        workspace_id=run.workspace_id, run_id=run.run_id,
                        payload={"failure_class": run.failure_class.value, "message": str(exc)})
        await db.commit()