from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, CandidateStatus

VISIBLE_SCOPES_BY_ROLE = {
    "member": {CandidateStatus.active, CandidateStatus.pending_review, CandidateStatus.rejected},
    "admin": {CandidateStatus.active, CandidateStatus.pending_review, CandidateStatus.rejected, CandidateStatus.hired},
    "owner": {CandidateStatus.active, CandidateStatus.pending_review, CandidateStatus.rejected, CandidateStatus.hired},
}


class CandidateAccessError(Exception):
    pass


async def get_visible_candidate(db: AsyncSession, *, workspace_id: int, candidate_id: int,
                                role: str) -> Candidate:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None or candidate.workspace_id != workspace_id:
        raise CandidateAccessError("资源不存在")
    if candidate.status not in VISIBLE_SCOPES_BY_ROLE.get(role, set()):
        raise CandidateAccessError("资源不存在")
    return candidate
