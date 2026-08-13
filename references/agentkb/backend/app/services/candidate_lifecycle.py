from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CandidateEvent, CandidateEventType


async def append_event(db: AsyncSession, *, candidate_id: int, event_type: CandidateEventType,
                       title: str, detail: dict | None = None, actor_id: int | None = None) -> None:
    db.add(CandidateEvent(candidate_id=candidate_id, event_type=event_type.value,
                          title=title, detail=detail or {}, actor_id=actor_id))