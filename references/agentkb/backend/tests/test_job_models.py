import pytest


@pytest.mark.asyncio
async def test_job_tables_roundtrip():
    from app.core.database import SessionLocal
    from app.models import (
        Job,
        JobRequirementOverride,
        JobRequirementRevision,
        JobStatus,
        OverrideAction,
        User,
        Workspace,
    )

    async with SessionLocal() as db:
        owner = User(email="jobm-owner@example.com", hashed_password="x", nickname="o")
        db.add(owner)
        await db.flush()
        ws = Workspace(name="jobm-ws", owner_id=owner.id)
        db.add(ws)
        await db.flush()
        job = Job(workspace_id=ws.id, name="前端开发工程师", description="5 年前端经验，精通 Vue",
                  headcount=3, city="杭州", salary_range="25-40k", status=JobStatus.open,
                  created_by=owner.id)
        db.add(job)
        await db.flush()
        rev = JobRequirementRevision(job_id=job.id, revision=1, description=job.description,
                                     parsed_ast=[{"field": "skills", "op": "contains", "value": ["Vue"],
                                                  "logic": "AND", "missing_policy": "exclude"}],
                                     schema_version="search/v1", prompt_version="job-req-prompt/v1",
                                     evidence={"skills": {"locator": "精通 Vue"}}, created_by=owner.id)
        db.add(rev)
        await db.flush()
        job.latest_revision_id = rev.id
        ov = JobRequirementOverride(job_id=job.id, revision_id=rev.id, field_path="skills",
                                    before_value=None, after_value={"field": "skills", "op": "contains",
                                                                    "value": ["Vue", "React"], "logic": "AND",
                                                                    "missing_policy": "exclude"},
                                    action=OverrideAction.override, actor_id=owner.id)
        db.add(ov)
        await db.commit()

        got = await db.get(Job, job.id)
        assert got.status is JobStatus.open
        assert got.latest_revision_id == rev.id
        rev2 = await db.get(JobRequirementRevision, rev.id)
        assert rev2.parsed_ast[0]["value"] == ["Vue"]
        assert rev2.evidence["skills"]["locator"] == "精通 Vue"
        ov2 = await db.get(JobRequirementOverride, ov.id)
        assert ov2.action is OverrideAction.override
        assert ov2.after_value["value"] == ["Vue", "React"]