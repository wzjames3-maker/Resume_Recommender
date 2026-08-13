from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import (
    Candidate,
    Job,
    JobRequirementOverride,
    JobRequirementRevision,
    ModelConfig,
    User,
    WorkspaceMember,
)
from app.services.audit import add_event
from app.services.crypto import decrypt_secret
from app.services.job_requirement import condition_key, resolve_effective_ast
from app.services.job_service import (
    JobConflictError,
    count_matching_candidates,
    create_job,
    list_jobs,
    update_job,
)
from app.services.model_client import ModelCallError
from app.services.search.schema import SearchSchemaError

router = APIRouter(prefix="/api/v1", tags=["jobs"])

MEMBER_VISIBLE = {"active", "pending_review", "rejected"}
ADMIN_VISIBLE = {"active", "pending_review", "rejected", "hired"}
# 条件主字段（condition_key 可用值）；expected_city 等副字段仅作 fields 配对，不可作 override 定位（I-3）
PRIMARY_CONDITION_FIELDS = {
    "skills", "years_experience", "city", "highest_degree",
    "expected_position", "name", "level", "domain", "management",
}


async def _member_info(db: AsyncSession, ws_id: int, user_id: int) -> WorkspaceMember:
    row = (await db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "资源不存在")
    return row


def _role_of(membership: WorkspaceMember) -> str:
    return membership.role.value if hasattr(membership.role, "value") else str(membership.role)


def _require_admin(role: str) -> None:
    if role not in ("admin", "owner"):
        raise HTTPException(403, "仅管理员可执行该操作")


async def _visible_job(db: AsyncSession, ws_id: int, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None or job.workspace_id != ws_id:
        raise HTTPException(404, "资源不存在")
    return job


async def _get_llm(db: AsyncSession, ws_id: int):
    from app.services.model_client import LLMClient

    cfg = (await db.execute(select(ModelConfig).where(
        ModelConfig.workspace_id == ws_id, ModelConfig.model_type == "llm"))).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(502, "工作区未配置 LLM 模型，无法解析岗位要求")
    return LLMClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


def _job_out(job: Job) -> dict:
    return {
        "job_id": job.id, "name": job.name, "status": job.status.value, "city": job.city,
        "headcount": job.headcount, "salary_range": job.salary_range,
        "description": job.description, "latest_revision_id": job.latest_revision_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


class JobCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=4000)
    headcount: int = Field(1, ge=1, le=999)
    city: str | None = Field(None, max_length=64)
    salary_range: str | None = Field(None, max_length=64)


@router.post("/workspaces/{ws_id}/jobs")
async def create_job_endpoint(ws_id: int, body: JobCreateRequest,
                              user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    role = _role_of(membership)
    llm = await _get_llm(db, ws_id)
    try:
        job, ast = await create_job(db, workspace_id=ws_id, name=body.name, description=body.description,
                                    headcount=body.headcount, city=body.city, salary_range=body.salary_range,
                                    actor_id=user.id, llm=llm)
    except ModelCallError as exc:
        raise HTTPException(502, f"岗位要求解析失败：{exc}")
    except SearchSchemaError as exc:
        raise HTTPException(502, f"岗位要求解析失败：{exc}")
    scopes = ADMIN_VISIBLE if role in ("admin", "owner") else MEMBER_VISIBLE
    match_count = await count_matching_candidates(db, ws_id, ast, scopes)
    await add_event(db, action="job.created", result="success", resource_type="job",
                    resource_id=str(job.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"name": job.name})
    await db.commit()
    return {
        "job": _job_out(job),
        "match_count": match_count,
        "match_prompt": f"有 {match_count} 位候选人可能匹配，要我列出来吗？" if match_count else None,
    }


@router.get("/workspaces/{ws_id}/jobs")
async def list_jobs_endpoint(ws_id: int, status: str | None = None, page: int = 1, page_size: int = 50,
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    total, items = await list_jobs(db, ws_id, status=status, page=page, page_size=page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/workspaces/{ws_id}/jobs/{job_id}")
async def get_job_detail(ws_id: int, job_id: int,
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    job = await _visible_job(db, ws_id, job_id)
    rev = await db.get(JobRequirementRevision, job.latest_revision_id)
    conditions, evidence = [], {}
    if rev is not None:
        overrides = (await db.execute(select(JobRequirementOverride).where(
            JobRequirementOverride.revision_id == rev.id).order_by(JobRequirementOverride.id))).scalars().all()
        conditions = resolve_effective_ast(rev, overrides)
        evidence = rev.evidence or {}
    return {
        "job": _job_out(job),
        "requirement": {
            "revision": rev.revision if rev else None,
            "schema_version": rev.schema_version if rev else None,
            "prompt_version": rev.prompt_version if rev else None,
            "conditions": conditions,
            "evidence": evidence,
        },
    }


class JobUpdateRequest(BaseModel):
    base_revision_id: int
    name: str | None = Field(None, max_length=128)
    description: str | None = Field(None, max_length=4000)
    headcount: int | None = Field(None, ge=1, le=999)
    city: str | None = Field(None, max_length=64)
    salary_range: str | None = Field(None, max_length=64)
    status: str | None = None


@router.patch("/workspaces/{ws_id}/jobs/{job_id}")
async def update_job_endpoint(ws_id: int, job_id: int, body: JobUpdateRequest,
                              user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    _require_admin(_role_of(membership))
    job = await _visible_job(db, ws_id, job_id)
    if body.status is not None and body.status not in ("open", "closed"):
        raise HTTPException(400, "status 必须为 open/closed")
    llm = await _get_llm(db, ws_id) if body.description is not None else None
    try:
        job, changed = await update_job(db, job=job, base_revision_id=body.base_revision_id,
                                        name=body.name, description=body.description,
                                        headcount=body.headcount, city=body.city,
                                        salary_range=body.salary_range, status=body.status,
                                        actor_id=user.id, llm=llm)
    except JobConflictError as exc:
        raise HTTPException(409, str(exc))
    except ModelCallError as exc:
        raise HTTPException(502, f"岗位要求解析失败：{exc}")
    except SearchSchemaError as exc:
        raise HTTPException(502, f"岗位要求解析失败：{exc}")
    await add_event(db, action="job.updated" if changed else "job.edited", result="success",
                    resource_type="job", resource_id=str(job.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"name": job.name, "status": job.status.value})
    await db.commit()
    return {"job": _job_out(job), "changed": changed}


class JobOverrideRequest(BaseModel):
    base_revision_id: int
    field_path: str = Field(..., max_length=128)
    action: str  # override / clear
    after_value: object | None = None


@router.post("/workspaces/{ws_id}/jobs/{job_id}/overrides")
async def override_job_requirement(ws_id: int, job_id: int, body: JobOverrideRequest,
                                   user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    _require_admin(_role_of(membership))
    job = await _visible_job(db, ws_id, job_id)
    if body.action not in ("override", "clear"):
        raise HTTPException(400, "action 必须为 override/clear")
    if body.field_path not in PRIMARY_CONDITION_FIELDS:
        raise HTTPException(400, "field_path 必须为条件主字段（skills/city/years_experience 等）")
    if body.base_revision_id != job.latest_revision_id:
        raise HTTPException(409, "岗位要求已被修改，请刷新后重试")
    rev = await db.get(JobRequirementRevision, job.latest_revision_id)
    if rev is None:
        raise HTTPException(409, "岗位要求尚未解析")
    overrides = (await db.execute(select(JobRequirementOverride).where(
        JobRequirementOverride.revision_id == rev.id).order_by(JobRequirementOverride.id))).scalars().all()
    before_ast = resolve_effective_ast(rev, overrides)
    before = next((c for c in before_ast if condition_key(c) == body.field_path), None)
    if body.action == "override":
        from app.services.search.schema import SearchSchemaError, validate_conditions
        if not isinstance(body.after_value, dict):
            raise HTTPException(400, "override 的 after_value 必须为条件对象")
        try:
            validate_conditions([body.after_value])
            if condition_key(body.after_value) != body.field_path:
                raise SearchSchemaError("条件主字段不一致")
        except SearchSchemaError as exc:
            raise HTTPException(400, str(exc))
    elif body.action == "clear" and before is None:
        raise HTTPException(400, "该字段当前无条件，无需清除")
    db.add(JobRequirementOverride(job_id=job.id, revision_id=rev.id, field_path=body.field_path,
                                  before_value=before, after_value=body.after_value,
                                  action=body.action, actor_id=user.id))
    await add_event(db, action="job.override", result="success", resource_type="job",
                    resource_id=str(job.id), workspace_id=ws_id, actor_id=user.id,
                    payload={"field_path": body.field_path, "action": body.action})
    await db.commit()
    overrides2 = (await db.execute(select(JobRequirementOverride).where(
        JobRequirementOverride.revision_id == rev.id).order_by(JobRequirementOverride.id))).scalars().all()
    return {"conditions": resolve_effective_ast(rev, overrides2)}


@router.get("/workspaces/{ws_id}/jobs/{job_id}/revisions")
async def list_job_revisions(ws_id: int, job_id: int,
                             user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member_info(db, ws_id, user.id)
    await _visible_job(db, ws_id, job_id)
    rows = (await db.execute(select(JobRequirementRevision).where(
        JobRequirementRevision.job_id == job_id).order_by(JobRequirementRevision.revision.desc()))).scalars().all()
    return {"items": [{
        "revision": r.revision, "description": r.description,
        "schema_version": r.schema_version, "prompt_version": r.prompt_version,
        "evidence": r.evidence, "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


async def _get_embedder(db: AsyncSession, ws_id: int):
    from app.services.model_client import EmbeddingClient

    cfg = (await db.execute(select(ModelConfig).where(
        ModelConfig.workspace_id == ws_id, ModelConfig.model_type == "embedding"))).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(502, "工作区未配置 embedding 模型")
    return EmbeddingClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


async def _get_rerank(db: AsyncSession, ws_id: int):
    from app.services.model_client import RerankClient

    cfg = (await db.execute(select(ModelConfig).where(
        ModelConfig.workspace_id == ws_id, ModelConfig.model_type == "rerank"))).scalar_one_or_none()
    if cfg is None:
        raise ModelCallError("未配置 rerank", retryable=False)
    return RerankClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


@router.get("/workspaces/{ws_id}/jobs/{job_id}/matches")
async def job_matches(ws_id: int, job_id: int, limit: int = 20,
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    membership = await _member_info(db, ws_id, user.id)
    role = _role_of(membership)
    limit = max(1, min(limit, 100))
    job = await _visible_job(db, ws_id, job_id)
    rev = await db.get(JobRequirementRevision, job.latest_revision_id)
    if rev is None:
        return {"items": [], "job_id": job.id}
    overrides = (await db.execute(select(JobRequirementOverride).where(
        JobRequirementOverride.revision_id == rev.id).order_by(JobRequirementOverride.id))).scalars().all()
    conditions = resolve_effective_ast(rev, overrides)
    if not conditions:
        return {"items": [], "job_id": job.id}
    qtext = f"{job.name}\n{job.description}"
    embedder = await _get_embedder(db, ws_id)
    qv = (await embedder.embed([qtext]))[0]

    from app.services.candidate_search import ALLOWED_SCOPES_BY_ROLE, search_candidates
    from app.services.search.cards import build_candidate_cards

    scopes = ALLOWED_SCOPES_BY_ROLE.get(role, set())
    top_k = max(20, min(max(1, limit), 100))
    hits = await search_candidates(db, ws_id, qv, qtext, conditions, scopes=scopes, top_k=top_k)
    # rerank 降级：不可用时保持混合检索顺序（J-8 链路）
    try:
        rerank = await _get_rerank(db, ws_id)
        rows = await db.execute(select(Candidate.id, Candidate.search_text).where(
            Candidate.id.in_([h.candidate_id for h in hits])))
        texts = {cid: (text or "")[:500] for cid, text in rows}
        docs = [texts.get(h.candidate_id, "") or f"candidate {h.candidate_id}" for h in hits]
        scores = await rerank.rerank(qtext, docs)
        if len(scores) == len(hits):
            hits = [h for _, h in sorted(zip(scores, hits), key=lambda x: x[0], reverse=True)]
    except ModelCallError:
        pass
    cards = await build_candidate_cards(db, [h.candidate_id for h in hits], conditions)
    return {"items": cards[:limit], "job_id": job.id}