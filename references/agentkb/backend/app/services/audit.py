import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


async def add_event(db: AsyncSession, *, action: str, result: str = "success",
                    resource_type: str = "unknown", resource_id: str | None = None,
                    actor_id: int | None = None, workspace_id: int | None = None,
                    run_id: str | None = None, revision_id: str | None = None,
                    before_hash: str | None = None, after_hash: str | None = None,
                    request_id: str | None = None, correlation_id: str | None = None,
                    payload: dict | None = None) -> AuditEvent:
    """不可变审计事件：只追加。任何调用方不得 update/delete 已写入事件。"""
    evt = AuditEvent(
        event_id=str(uuid.uuid4()), request_id=request_id, correlation_id=correlation_id,
        actor_id=actor_id, workspace_id=workspace_id, resource_type=resource_type,
        resource_id=resource_id, action=action, result=result,
        before_hash=before_hash, after_hash=after_hash,
        run_id=run_id, revision_id=revision_id, payload=payload or {},
    )
    db.add(evt)
    return evt