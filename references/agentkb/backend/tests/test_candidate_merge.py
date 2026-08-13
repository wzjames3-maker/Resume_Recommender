import pytest


@pytest.mark.asyncio
async def test_merge_candidates_reparents_and_uses_latest_revision():
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import (
        Candidate,
        CandidateEvent,
        CandidateEventType,
        CandidateOverride,
        CandidateRevision,
        CandidateStatus,
        OverrideAction,
        ResumeFile,
        User,
        Workspace,
    )
    from app.services.candidate_merge import merge_candidates

    async with SessionLocal() as db:
        owner = User(email="cm-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cm-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()

        primary = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                            structured_data={"city": "杭州"}, search_text="杭州",
                            phone_hash="h1", email_hash=None)
        db.add(primary)
        await db.flush()
        rev_old = CandidateRevision(candidate_id=primary.id, run_id="cm-old", revision_id="cm-old:rev1",
                                    candidate_json={"name": "张三", "city": "杭州"}, evidence={},
                                    profile_json={"values": {"level": "Mid"}, "evidence": {}})
        db.add(rev_old)
        await db.flush()
        primary.latest_revision_id = rev_old.id
        db.add(CandidateOverride(candidate_id=primary.id, revision_id="cm-old:rev1", field_path="city",
                                 before_value="杭州", after_value="上海", action=OverrideAction.override, actor_id=owner.id))

        absorbed = Candidate(workspace_id=ws.id, status=CandidateStatus.pending_review, name="张三",
                             structured_data={"skills": ["Java"], "city": "北京"}, search_text="Java",
                             phone_hash="h2", email_hash="e2")
        db.add(absorbed)
        await db.flush()
        rev_new = CandidateRevision(candidate_id=absorbed.id, run_id="cm-new", revision_id="cm-new:rev1",
                                    candidate_json={"name": "张三", "skills": ["Java"], "city": "北京"}, evidence={},
                                    profile_json={"values": {"level": "Senior"}, "evidence": {}})
        db.add(rev_new)
        await db.flush()
        absorbed.latest_revision_id = rev_new.id
        db.add(ResumeFile(run_id="cm-new", candidate_id=absorbed.id, file_hash="f1", storage_key="k1",
                          format="pdf", file_size=1, content_type="application/pdf"))

        await db.commit()
        p_id, a_id, base = primary.id, absorbed.id, primary.latest_revision_id

        merged = await merge_candidates(db, primary=primary, absorbed=absorbed,
                                        base_revision_id=base, actor_id=owner.id)
        await db.commit()

        got = await db.get(Candidate, merged.id)
        assert got.latest_revision_id == rev_new.id  # 最新 revision 成为主体 base
        assert got.structured_data["skills"] == ["Java"]
        assert got.phone_hash == "h1"  # 主体已有 phone，保留
        assert got.email_hash == "e2"  # 主体无 email，用被并入者补齐
        # 被并入者软删
        absorbed2 = await db.get(Candidate, a_id)
        assert absorbed2.status is CandidateStatus.deleted
        assert absorbed2.deleted_until is not None
        # revision 全部重挂到主体
        owners = (await db.execute(
            select(CandidateRevision.candidate_id)
            .where(CandidateRevision.id.in_([rev_old.id, rev_new.id])))).scalars().all()
        assert set(owners) == {p_id}
        # merged 事件
        evt = (await db.execute(
            select(CandidateEvent)
            .where(CandidateEvent.candidate_id == p_id, CandidateEvent.event_type == CandidateEventType.merged))).scalar_one()
        assert evt.detail["absorbed_id"] == a_id


@pytest.mark.asyncio
async def test_merge_conflict_and_hired_rejected():
    from app.core.database import SessionLocal
    from app.models import Candidate, CandidateStatus, User, Workspace
    from app.services.candidate_merge import (
        MergeConflictError,
        MergeError,
        merge_candidates,
    )

    async with SessionLocal() as db:
        owner = User(email="cm2-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="cm2-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        primary = Candidate(workspace_id=ws.id, status=CandidateStatus.active, name="张三",
                            structured_data={}, search_text="")
        absorbed = Candidate(workspace_id=ws.id, status=CandidateStatus.hired, name="张三",
                             structured_data={}, search_text="")
        db.add_all([primary, absorbed])
        await db.commit()

        with pytest.raises(MergeError, match="入职员工"):
            await merge_candidates(db, primary=primary, absorbed=absorbed,
                                   base_revision_id=primary.latest_revision_id, actor_id=owner.id)

        # 乐观锁 409 语义
        absorbed2 = Candidate(workspace_id=ws.id, status=CandidateStatus.pending_review, name="王五",
                              structured_data={}, search_text="")
        db.add(absorbed2)
        await db.commit()
        with pytest.raises(MergeConflictError):
            await merge_candidates(db, primary=primary, absorbed=absorbed2,
                                   base_revision_id=999, actor_id=owner.id)