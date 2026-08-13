from dataclasses import dataclass

from sqlalchemy import select

from app.models import Candidate
from app.services.audit import add_event
from app.services.candidate_search import ALLOWED_SCOPES_BY_ROLE, search_candidates
from app.services.crypto import decrypt_secret
from app.services.model_client import (
    EmbeddingClient,
    LLMClient,
    ModelCallError,
    RerankClient,
)
from app.services.search.cards import build_candidate_cards
from app.services.search.context import merge_follow_up
from app.services.search.extractor import extract_search_intent

REFUSAL_INTENTS = {"write_request"}  # statistics 已落地（P9 F11）
NON_SEARCH_INTENTS = {"chit_chat", "out_of_scope"}
MAX_TOP_K = 100  # 数量意图召回上限（防滥用）


@dataclass
class SearchOutcome:
    intent: str
    cards: list[dict]
    summary: str
    context: dict | None
    job_candidates: list | None = None
    statistics: dict | None = None


async def _get_model_client(db, workspace_id: int, model_type: str):
    from app.models import ModelConfig

    cfg = (await db.execute(select(ModelConfig).where(
        ModelConfig.workspace_id == workspace_id, ModelConfig.model_type == model_type))).scalar_one_or_none()
    if cfg is None:
        raise ModelCallError(f"workspace 未配置 {model_type} 模型", retryable=False)
    return cfg


async def _get_llm(db, workspace_id: int):
    cfg = await _get_model_client(db, workspace_id, "llm")
    return LLMClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


async def _get_embedder(db, workspace_id: int):
    cfg = await _get_model_client(db, workspace_id, "embedding")
    return EmbeddingClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


async def _get_rerank(db, workspace_id: int):
    cfg = await _get_model_client(db, workspace_id, "rerank")
    return RerankClient(cfg.base_url, decrypt_secret(cfg.api_key_enc), cfg.model_name)


async def _rerank_hits(db, workspace_id: int, utterance: str, hits) -> tuple[list, bool]:
    """S-1：rerank 排序；rerank 不可用降级为 RRF 顺序返回 (hits, rerank_used=False)。"""
    if not hits:
        return hits, False
    try:
        rerank = await _get_rerank(db, workspace_id)
    except ModelCallError:
        return hits, False
    # 文档用候选人 search_text（含技能/岗位/本地摘要），比「姓名+命中标签」提供更强语义信号
    rows = await db.execute(select(Candidate.id, Candidate.search_text).where(
        Candidate.id.in_([h.candidate_id for h in hits])))
    texts = {cid: (text or "")[:500] for cid, text in rows}
    docs = [texts.get(h.candidate_id, "") or f"candidate {h.candidate_id}" for h in hits]
    try:
        scores = await rerank.rerank(utterance, docs)
    except ModelCallError:
        return hits, False
    if len(scores) != len(hits):
        return hits, False
    ordered = [h for _, h in sorted(zip(scores, hits), key=lambda x: x[0], reverse=True)]
    return ordered, True


def _refusal_text(intent: str) -> str:
    return {
        "write_request": "写请求（指派/打标/修正等）不在此对话中执行，请到工作台完成。",
    }[intent]


def _non_search_text(intent: str) -> str:
    return {
        "chit_chat": "我是招聘搜人助手，可以帮你按技能、年限、城市、学历等条件找人。",
        "out_of_scope": "这个问题超出搜人范围，我只能基于人才库做候选人检索。",
    }[intent]


async def run_search_flow(db, *, workspace_id: int, actor_role: str, actor_id: int,
                          utterance: str, prior_context: dict | None) -> SearchOutcome:
    llm = await _get_llm(db, workspace_id)
    prior = prior_context or {}
    parsed = await extract_search_intent(llm, utterance, prior.get("conditions"), prior.get("job_candidates"))

    if parsed.intent in REFUSAL_INTENTS:
        await add_event(db, action="search.intent.refusal", result="success",
                        resource_type="search", workspace_id=workspace_id, actor_id=actor_id,
                        payload={"intent": parsed.intent})
        await db.commit()
        return SearchOutcome(intent=parsed.intent, cards=[], summary=_refusal_text(parsed.intent), context=None)

    if parsed.intent in NON_SEARCH_INTENTS:
        await add_event(db, action="search.intent.non_search", result="success",
                        resource_type="search", workspace_id=workspace_id, actor_id=actor_id,
                        payload={"intent": parsed.intent})
        await db.commit()
        return SearchOutcome(intent=parsed.intent, cards=[], summary=_non_search_text(parsed.intent), context=None)

    if parsed.intent == "job_search":
        return await _run_job_search(db, workspace_id=workspace_id, actor_role=actor_role,
                                     actor_id=actor_id, utterance=utterance, parsed=parsed, prior=prior)

    if parsed.intent == "statistics":
        return await _run_statistics(db, workspace_id=workspace_id, actor_role=actor_role,
                                     actor_id=actor_id, parsed=parsed, prior=prior)

    # search / follow_up
    prior_conds = (prior_context or {}).get("conditions") or []
    conditions = merge_follow_up(prior_conds, parsed.conditions) if parsed.intent == "follow_up" else parsed.conditions
    if parsed.interview_result:
        conditions = [*conditions, {"field": "interview_result", "op": "eq",
                                    "value": parsed.interview_result, "logic": "AND",
                                    "missing_policy": "exclude"}]
    if parsed.assignment_status:
        conditions = [*conditions, {"field": "assignment_status", "op": "eq",
                                    "value": parsed.assignment_status, "logic": "AND",
                                    "missing_policy": "exclude"}]
    pool_scope = parsed.pool_scope or (prior_context or {}).get("pool_scope") or "active"
    if parsed.interview_result:
        pool_scope = None
    elif parsed.assignment_status == "hired":
        pool_scope = "hired"
    elif parsed.assignment_status in {"rejected", "offer_rejected", "closed_after_hire", "closed_by_job"}:
        pool_scope = "rejected"
    elif parsed.interview_result == "failed":
        pool_scope = "rejected"
    requested = parsed.requested_count if parsed.requested_count is not None else (prior_context or {}).get("requested_count")

    allowed = ALLOWED_SCOPES_BY_ROLE.get(actor_role, set())
    requested_scopes = (allowed if parsed.interview_result else {pool_scope}) \
        if (parsed.assignment_status or parsed.interview_result) and not parsed.pool_scope else ({pool_scope} if pool_scope else allowed)
    scopes = requested_scopes & allowed
    if not scopes:
        await add_event(db, action="search.pool.denied", result="denied",
                        resource_type="search", workspace_id=workspace_id, actor_id=actor_id,
                        payload={"requested": pool_scope, "role": actor_role})
        await db.commit()
        return SearchOutcome(intent="search", cards=[], summary="无权限查询该人才池。", context=None)

    # Critical-2：数量意图按 requested_count 放大召回（上限 MAX_TOP_K），返回时截断
    top_k = max(20, min(requested or 20, MAX_TOP_K))
    embedder = await _get_embedder(db, workspace_id)
    qv = (await embedder.embed([utterance]))[0]
    hits = await search_candidates(db, workspace_id, qv, utterance, conditions, scopes=scopes, top_k=top_k,
                                   assignment_history=parsed.assignment_history)
    hits, rerank_used = await _rerank_hits(db, workspace_id, utterance, hits)
    cards = await build_candidate_cards(db, [h.candidate_id for h in hits], conditions)
    if requested and len(cards) > requested:
        cards = cards[:requested]

    if requested:
        returned = len(cards)
        summary = (f"仅找到 {returned} 位匹配候选人（请求 {requested} 位）。" if returned < requested
                   else f"已返回 {requested} 位匹配候选人。")
    elif not cards:
        summary = "未找到匹配的候选人，可尝试放宽技能、年限或城市条件。"
    else:
        summary = f"找到 {len(cards)} 位匹配候选人，按相关度排序。"

    context = {"conditions": conditions, "pool_scope": pool_scope, "requested_count": requested,
               "assignment_history": parsed.assignment_history}
    await add_event(db, action="search.executed", result="success",
                    resource_type="search", workspace_id=workspace_id, actor_id=actor_id,
                    payload={"intent": parsed.intent, "hit_count": len(cards), "rerank": rerank_used})
    await db.commit()
    return SearchOutcome(intent=parsed.intent, cards=cards, summary=summary, context=context)

async def _run_job_search(db, *, workspace_id: int, actor_role: str, actor_id: int,
                          utterance: str, parsed, prior: dict) -> SearchOutcome:
    from app.models import (
        JobRequirementOverride,
        JobRequirementRevision,
        JobStatus,
    )
    from app.services.job_requirement import resolve_effective_ast
    from app.services.job_service import resolve_job

    # 只在本轮未提供任何职位引用时才回退上一轮 job_id（C-1：新 job_title 不得被旧 job_id 覆盖）
    job_id = parsed.job_id
    if job_id is None and not parsed.job_title:
        job_id = prior.get("job_id")
    job, candidates, needs_confirmation = await resolve_job(
        db, workspace_id, job_id=job_id, job_title=parsed.job_title)

    if needs_confirmation:
        await add_event(db, action="search.job.ambiguous", result="success", resource_type="job",
                        workspace_id=workspace_id, actor_id=actor_id,
                        payload={"candidates": len(candidates)})
        await db.commit()
        ctx = {"conditions": [], "pool_scope": parsed.pool_scope or prior.get("pool_scope") or "active",
               "requested_count": parsed.requested_count, "job_id": None,
               "job_candidates": candidates}
        return SearchOutcome(intent="job_search", cards=[],
                             summary=f"找到 {len(candidates)} 个名称相近的在招职位，请选择：",
                             context=ctx, job_candidates=candidates)

    if job is None:
        await add_event(db, action="search.job.not_found", result="success", resource_type="job",
                        workspace_id=workspace_id, actor_id=actor_id, payload={})
        await db.commit()
        return SearchOutcome(intent="job_search", cards=[],
                             summary="未找到匹配的在招职位，请确认职位名称。", context=None)

    if job.status is JobStatus.closed:
        return SearchOutcome(intent="job_search", cards=[],
                             summary="该职位已关闭，无法按它检索候选人。", context=None)

    rev = await db.get(JobRequirementRevision, job.latest_revision_id)
    if rev is None:
        return SearchOutcome(intent="job_search", cards=[],
                             summary="该职位岗位要求尚未解析，请联系管理员。", context=None)
    overrides = (await db.execute(select(JobRequirementOverride).where(
        JobRequirementOverride.revision_id == rev.id).order_by(JobRequirementOverride.id))).scalars().all()
    ast = resolve_effective_ast(rev, overrides)
    conditions = ast + parsed.conditions
    if parsed.interview_result:
        conditions = [*conditions, {"field": "interview_result", "op": "eq",
                                    "value": parsed.interview_result, "logic": "AND",
                                    "missing_policy": "exclude"}]
    if parsed.assignment_status:
        conditions = [*conditions, {"field": "assignment_status", "op": "eq",
                                    "value": parsed.assignment_status, "logic": "AND",
                                     "missing_policy": "exclude"}]
    pool_scope = parsed.pool_scope or prior.get("pool_scope") or "active"
    if parsed.interview_result:
        pool_scope = None
    elif parsed.assignment_status == "hired":
        pool_scope = "hired"
    elif parsed.assignment_status in {"rejected", "offer_rejected", "closed_after_hire", "closed_by_job"}:
        pool_scope = "rejected"
    elif parsed.interview_result == "failed":
        pool_scope = "rejected"

    allowed = ALLOWED_SCOPES_BY_ROLE.get(actor_role, set())
    requested_scopes = (allowed if parsed.interview_result else {pool_scope}) \
        if (parsed.assignment_status or parsed.interview_result) and not parsed.pool_scope else ({pool_scope} if pool_scope else allowed)
    scopes = requested_scopes & allowed
    if not scopes:
        await add_event(db, action="search.pool.denied", result="denied",
                        resource_type="search", workspace_id=workspace_id, actor_id=actor_id,
                        payload={"requested": pool_scope, "role": actor_role})
        await db.commit()
        return SearchOutcome(intent="job_search", cards=[], summary="无权限查询该人才池。", context=None)

    requested = parsed.requested_count if parsed.requested_count is not None else prior.get("requested_count")
    top_k = max(20, min(requested or 20, MAX_TOP_K))
    embedder = await _get_embedder(db, workspace_id)
    qtext = f"{job.name}\n{job.description}"
    qv = (await embedder.embed([qtext]))[0]
    hits = await search_candidates(db, workspace_id, qv, qtext, conditions, scopes=scopes, top_k=top_k,
                                   assignment_history=parsed.assignment_history)
    hits, rerank_used = await _rerank_hits(db, workspace_id, qtext, hits)
    cards = await build_candidate_cards(db, [h.candidate_id for h in hits], conditions)
    if requested and len(cards) > requested:
        cards = cards[:requested]

    if requested:
        returned = len(cards)
        summary = (f"职位「{job.name}」仅找到 {returned} 位匹配候选人（请求 {requested} 位）。"
                   if returned < requested else f"职位「{job.name}」已返回 {requested} 位匹配候选人。")
    elif not cards:
        summary = f"职位「{job.name}」暂无匹配候选人，可放宽岗位要求或切换职位。"
    else:
        summary = f"职位「{job.name}」找到 {len(cards)} 位匹配候选人，按相关度排序。"

    context = {"conditions": conditions, "pool_scope": pool_scope,
               "requested_count": requested, "job_id": job.id, "job_candidates": None,
               "assignment_history": parsed.assignment_history}
    await add_event(db, action="search.job.executed", result="success", resource_type="search",
                    workspace_id=workspace_id, actor_id=actor_id,
                    payload={"job_id": job.id, "hit_count": len(cards), "rerank": rerank_used})
    await db.commit()
    return SearchOutcome(intent="job_search", cards=cards, summary=summary, context=context)


DIMENSION_LABELS = {
    "city": "城市", "expected_city": "期望城市", "highest_degree": "学历",
    "years_experience": "年限", "expected_position": "期望岗位",
    "level": "职级", "domain": "领域", "management": "管理能力",
}


async def _run_statistics(db, *, workspace_id: int, actor_role: str, actor_id: int,
                          parsed, prior: dict) -> SearchOutcome:
    from app.services.search.statistics import compute_statistics

    pool_scope = parsed.pool_scope or prior.get("pool_scope") or "active"
    if parsed.interview_result:
        pool_scope = None
    elif parsed.assignment_status == "hired":
        pool_scope = "hired"
    elif parsed.assignment_status in {"rejected", "offer_rejected"}:
        pool_scope = "rejected"
    elif parsed.assignment_status in {"closed_after_hire", "closed_by_job"}:
        pool_scope = "active"
    allowed = ALLOWED_SCOPES_BY_ROLE.get(actor_role, set())
    requested_scopes = allowed if parsed.interview_result else ({pool_scope} if pool_scope else allowed)
    scopes = requested_scopes & allowed
    if not scopes:
        await add_event(db, action="search.pool.denied", result="denied",
                        resource_type="search", workspace_id=workspace_id, actor_id=actor_id,
                        payload={"requested": pool_scope, "role": actor_role})
        await db.commit()
        return SearchOutcome(intent="statistics", cards=[], summary="无权限查询该人才池。", context=None)

    stat_conditions = list(parsed.conditions)
    if parsed.interview_result:
        stat_conditions.append({"field": "interview_result", "op": "eq", "value": parsed.interview_result,
                                "logic": "AND", "missing_policy": "exclude"})
    if parsed.assignment_status:
        stat_conditions.append({"field": "assignment_status", "op": "eq", "value": parsed.assignment_status,
                                "logic": "AND", "missing_policy": "exclude"})
    stats = await compute_statistics(db, workspace_id=workspace_id, conditions=stat_conditions,
                                     scopes=scopes, group_by=parsed.stat_group_by,
                                     assignment_history=parsed.assignment_history)
    if stats["dimension"] and stats["distribution"]:
        label = DIMENSION_LABELS.get(stats["dimension"], stats["dimension"])
        parts = "、".join(f"{g['key']} {g['count']}" for g in stats["distribution"])
        summary = f"人才库中共有 {stats['count']} 位候选人符合条件。{label}分布：{parts}。"
    else:
        summary = f"人才库中共有 {stats['count']} 位候选人符合条件。"

    context = {"conditions": parsed.conditions, "pool_scope": pool_scope,
               "assignment_history": parsed.assignment_history}
    await add_event(db, action="search.statistics.executed", result="success",
                    resource_type="search", workspace_id=workspace_id, actor_id=actor_id,
                    payload={"count": stats["count"], "dimension": stats["dimension"]})
    await db.commit()
    return SearchOutcome(intent="statistics", cards=[], summary=summary, context=context, statistics=stats)
