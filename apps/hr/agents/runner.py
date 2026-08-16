# coding=utf-8
"""
    @project: MaxKB
    @file： runner.py
    @date：2026/8/17
    @desc: Screening Agent Runner（PRD-AGENT-RAG §4/§6）：
           固定顺序工具编排（get_job → get_candidate_overview → structured_filter → search_resumes）
           + 单次 LLM 结构化评估 + 服务端评分派生建议动作 + propose 写 HrAgentProposal。
           幂等/并发护栏/降级：事件触发 celery-once 防重；LLM 失败 run=FAILED，业务零影响。
"""
import json
import time
import uuid

from django.utils import timezone

from common.exception.app_exception import AppApiException
from hr.agents import context, scoring
from hr.agents.proposals import expire_pending_proposals, propose
from hr.models import (
    Application,
    ApplicationStatus,
    CandidateSkill,
    HrAgentRun,
    HrAgentRunStatus,
    HrAgentTriggerType,
    HrConfig,
    RelationType,
)
from hr.services.audit import write_audit_log
from hr.services.resume_search import search_resumes
from hr.services.skill_normalize import normalize_skill
from models_provider.tools import get_model_by_id, get_model_instance_by_model_workspace_id

_SYSTEM_USER_ID = uuid.UUID(int=0)
_PROMPT_VERSION = "screening-v1"
_AGENT_TYPE = "SCREENING"
_MAX_SEARCHES = 3
_EVENT_RELATION_TYPES = (RelationType.APPLY, RelationType.REFERRAL)

_SCREENING_PROMPT = """你是招聘初筛助手，对候选人 X 与职位 Y 做人岗匹配评估。
输入：
<job>{job}</job>
<candidate>{candidate}</candidate>
<hard_conditions>{hard_conditions}</hard_conditions>
<evidence>{evidence}</evidence>

要求：
1. hard_conditions 已由结构化核对给出，不要重复判断，也不要在维度里推翻它们。
2. 对每条软性条件从 <evidence> 中检索候选人相关经历片段作为证据；证据必须摘录原文（excerpt）。
3. 只输出一个 JSON 对象（不要输出任何其他内容），结构如下：
{{
  "dimensions": [
    {{
      "name": "维度名",
      "verdict": "该维度的评估结论（必须引用证据或说明证据不足）",
      "evidence": [{{"paragraph_id": "", "excerpt": "原文摘录（脱敏 chunk）", "relevance": 0.0}}],
      "confidence": 0.0
    }}
  ],
  "concerns": ["风险点1"],
  "clarifying_questions": ["需要向候选人澄清的问题"]
}}
4. 维度名只能取以下白名单之一：技能匹配、经验相关性、工作年限、城市、学历（学历仅当职位明确要求时使用）。
5. 每个维度的结论必须引用至少一条证据；证据不足时 confidence 必须 < 0.5 并如实说明。
6. **不得输出 score 或 suggested_action**（由系统派生）；不得编造简历中不存在的内容。
7. 禁止以姓名、性别、年龄、婚育、民族、院校出身作为评价依据。
"""


def _config(workspace_id):
    config = HrConfig.objects.filter(workspace_id=workspace_id).first()
    if config is None:
        config = HrConfig.objects.create(workspace_id=workspace_id, llm_model_id="")
    return config


def _load_llm(workspace_id, config):
    if not config.llm_model_id:
        return None, ""
    try:
        model = get_model_by_id(config.llm_model_id, workspace_id)
    except Exception:
        return None, ""
    if getattr(model, "model_type", None) != "LLM":
        return None, ""
    try:
        instance = get_model_instance_by_model_workspace_id(config.llm_model_id, workspace_id)
    except Exception:
        return None, ""
    return instance, getattr(model, "model_name", "") or config.llm_model_id


def structured_filter(job, candidate):
    """硬条件逐条核对（技能/城市；学历与年限职位未声明时跳过）。"""
    conditions = []
    skill_norms = {normalize_skill(skill) for skill in (job.skill_requirements or [])}
    if skill_norms:
        owned_raw = set(
            CandidateSkill.objects.filter(candidate=candidate).values_list("skill_norm", flat=True)
        )
        if not owned_raw:
            # 技能归一表未回填时回退候选人 skills 字段（与 resume_search 空表跳过口径一致）
            owned_raw = {normalize_skill(skill) for skill in (candidate.skills or [])}
        owned = owned_raw
        matched = sorted(skill_norms & owned)
        missing = sorted(skill_norms - owned)
        conditions.append({
            "requirement": "技能：" + "、".join(job.skill_requirements),
            "field": "skills",
            "met": bool(matched),
            "detail": f"命中技能：{('、'.join(matched)) or '无'}；缺失：{('、'.join(missing)) or '无'}",
        })
    if job.city:
        cities = {candidate.current_city, candidate.target_city}
        met = bool(cities & {job.city})
        conditions.append({
            "requirement": f"城市：{job.city}",
            "field": "city",
            "met": met,
            "detail": f"候选人现居 {candidate.current_city or '未知'}，目标城市 {candidate.target_city or '未知'}",
        })
    hard_met = bool(conditions) and all(condition["met"] for condition in conditions)
    return {"conditions": conditions, "hard_met": hard_met}


def _collect_evidence(workspace_id, job, candidate, document_ids):
    """在该候选人简历文档集内做软条件语义检索（复用 RRF+rerank，召回入口限集）。"""
    queries = []
    if job.skill_requirements:
        queries.append(" ".join(job.skill_requirements))
    if job.name:
        queries.append(job.name)
    if job.description:
        queries.append(job.description[:200])
    results = []
    for query in queries[:_MAX_SEARCHES]:
        try:
            raw = search_resumes(
                workspace_id,
                query,
                top_k=5,
                mode="phrase",
                hr_role="VIEWER",
                user_id=None,
                llm_model=None,
                rerank_model=None,
                candidate_id=str(candidate.id),
                document_ids=document_ids,
            )
        except AppApiException:
            continue
        projected = context.search_to_llm(raw)
        results.append({"query": query, "items": projected["items"], "meta": projected["meta"]})
    return results


def _invoke_llm(model, prompt):
    response = model.invoke(prompt)
    content = getattr(response, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty LLM response")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON from LLM") from exc


def _validate_facts(data):
    """结构化校验 LLM 评估事实；失败抛 ValueError（触发重试）。"""
    if not isinstance(data, dict):
        raise ValueError("facts must be an object")
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError("dimensions must be a non-empty list")
    cleaned = []
    for dimension in dimensions:
        if not isinstance(dimension, dict) or not str(dimension.get("name") or "").strip():
            continue
        evidence = []
        for item in (dimension.get("evidence") or []):
            if isinstance(item, dict):
                evidence.append({
                    "paragraph_id": item.get("paragraph_id"),
                    "excerpt": str(item.get("excerpt") or "")[:500],
                    "relevance": float(item.get("relevance", 0) or 0) if _is_number(item.get("relevance")) else 0.0,
                })
        cleaned.append({
            "name": str(dimension["name"]).strip(),
            "verdict": str(dimension.get("verdict") or "")[:2000],
            "evidence": evidence,
            "confidence": float(dimension.get("confidence", 0) or 0),
        })
    if not cleaned:
        raise ValueError("no valid dimensions")
    return {
        "dimensions": cleaned,
        "concerns": [str(item)[:500] for item in (data.get("concerns") or []) if isinstance(item, str)][:10],
        "clarifying_questions": [str(item)[:500] for item in (data.get("clarifying_questions") or []) if isinstance(item, str)][:10],
    }


def _is_number(value):
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _guard_limits(workspace_id, config):
    """并发与速率护栏：超限返回跳过原因，否则 None。"""
    concurrent = HrAgentRun.objects.filter(
        workspace_id=workspace_id,
        agent_type=_AGENT_TYPE,
        status__in=[HrAgentRunStatus.PENDING, HrAgentRunStatus.RUNNING],
    ).count()
    if concurrent >= config.agent_max_concurrent_runs:
        return f"concurrent run limit reached ({config.agent_max_concurrent_runs})"
    since = timezone.now() - timezone.timedelta(hours=1)
    recent = HrAgentRun.objects.filter(
        workspace_id=workspace_id, agent_type=_AGENT_TYPE, create_time__gte=since
    ).count()
    if recent >= config.agent_run_rate_limit:
        return f"rate limit reached ({config.agent_run_rate_limit}/hour)"
    return None


def run_screening_agent(application_id, trigger_type=HrAgentTriggerType.EVENT, user_id=None):
    """执行一次 Screening Agent 运行；任何失败 run=FAILED，业务零影响。"""
    application = Application.objects.filter(id=application_id).select_related(
        "candidate", "job", "current_stage"
    ).first()
    if application is None:
        return None
    workspace_id = application.workspace_id
    actor_id = user_id or application.user_id or _SYSTEM_USER_ID
    config = _config(workspace_id)
    if not config.agent_enable_screening:
        return _write_skipped_run(workspace_id, actor_id, application, trigger_type, "agent disabled")
    if application.status != ApplicationStatus.ACTIVE:
        return _write_skipped_run(workspace_id, actor_id, application, trigger_type, "application not active")
    if application.current_stage is None or application.current_stage.key != "APPLIED":
        return _write_skipped_run(workspace_id, actor_id, application, trigger_type, "not at APPLIED stage")
    if trigger_type == HrAgentTriggerType.EVENT and application.relation_type not in _EVENT_RELATION_TYPES:
        return _write_skipped_run(workspace_id, actor_id, application, trigger_type, "relation_type not APPLY/REFERRAL")

    skip_reason = _guard_limits(workspace_id, config)
    if skip_reason:
        return _write_skipped_run(workspace_id, actor_id, application, trigger_type, skip_reason)

    expire_pending_proposals(workspace_id, application_id)
    run = HrAgentRun.objects.create(
        workspace_id=workspace_id,
        agent_type=_AGENT_TYPE,
        trigger_type=trigger_type,
        ref_object_type="APPLICATION",
        ref_object_id=str(application.id),
        status=HrAgentRunStatus.RUNNING,
        input_meta={
            "application_id": str(application.id),
            "job_id": str(application.job_id),
            "candidate_id": str(application.candidate_id),
            "channel": application.channel,
            "stage_key": application.current_stage.key if application.current_stage else "",
        },
        prompt_version=_PROMPT_VERSION,
        user_id=actor_id,
    )
    started = time.monotonic()
    trace = []
    try:
        model, model_name = _load_llm(workspace_id, config)
        if model is None:
            raise RuntimeError("LLM model is not configured or unavailable")

        # 工具 ① get_job
        t0 = time.monotonic()
        job_ctx = context.job_to_llm(application.job)
        trace.append({"tool": "get_job", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})
        # 工具 ② get_candidate_overview
        t0 = time.monotonic()
        candidate_ctx = context.candidate_to_llm(application.candidate)
        trace.append({"tool": "get_candidate_overview", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})
        # 工具 ③ structured_filter
        t0 = time.monotonic()
        filter_result = structured_filter(application.job, application.candidate)
        filter_ctx = context.structured_filter_to_llm(filter_result)
        trace.append({"tool": "structured_filter", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(filter_result["conditions"])})
        # 工具 ④ search_resumes（候选人文档集限定）
        document_ids = [
            str(doc_id) for doc_id in
            application.candidate.resume_files.values_list("document_id", flat=True)
        ] if hasattr(application.candidate, "resume_files") else []
        from hr.models import ResumeFile

        if not document_ids:
            document_ids = [
                str(doc_id) for doc_id in ResumeFile.objects.filter(
                    candidate=application.candidate, document_id__isnull=False
                ).values_list("document_id", flat=True)
            ]
        t0 = time.monotonic()
        evidence = _collect_evidence(workspace_id, application.job, application.candidate, document_ids)
        trace.append({"tool": "search_resumes", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(evidence)})

        prompt = _SCREENING_PROMPT.format(
            job=json.dumps(job_ctx, ensure_ascii=False),
            candidate=json.dumps(candidate_ctx, ensure_ascii=False),
            hard_conditions=json.dumps(filter_ctx, ensure_ascii=False),
            evidence=json.dumps(evidence, ensure_ascii=False),
        )
        facts = None
        last_error = ""
        for _attempt in range(2):
            try:
                facts = _validate_facts(_invoke_llm(model, prompt))
                break
            except (ValueError, TypeError, KeyError) as exc:
                last_error = str(exc)
        if facts is None:
            raise RuntimeError(f"LLM output validation failed: {last_error}")

        evidence_available = any(item.get("items") for item in evidence)
        if evidence_available:
            decision = scoring.derive_decision(
                facts, filter_result["hard_met"], bands=config.agent_score_bands or {},
                score_version=config.agent_score_version or "v1",
            )
        else:
            # §6.3：检索空结果 → 禁止无证据高分，强制 HOLD + 原因
            decision = {
                "score": None,
                "suggested_action": "HOLD",
                "hard_met": filter_result["hard_met"],
                "evidence_ok": False,
                "required_dims_ok": False,
                "score_version": config.agent_score_version or "v1",
                "dimension_details": [],
                "warnings": [{"reason": "no evidence from resume search"}],
            }
        payload = {
            "stage_key": application.current_stage.key if application.current_stage else "",
            "hard_conditions": filter_result["conditions"],
            "dimensions": facts["dimensions"],
            "concerns": facts["concerns"],
            "clarifying_questions": facts["clarifying_questions"],
            "decision": decision,
        }
        proposal = propose(
            workspace_id,
            run,
            target_id=str(application.id),
            action=payload["decision"]["suggested_action"],
            payload_json=payload,
        )
        run.output_json = payload
        run.status = HrAgentRunStatus.SUCCEEDED
        run.llm_model = model_name
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["output_json", "status", "llm_model", "tool_trace", "duration_ms", "update_time"])
        write_audit_log(
            workspace_id, actor_id, "AGENT_RUN", "APPLICATION", application.id,
            detail={
                "agent_type": _AGENT_TYPE, "trigger": trigger_type,
                "action": payload["decision"]["suggested_action"],
                "score": payload["decision"]["score"],
            },
            trace_id=run.id,
        )
        return _run_output(run, proposal)
    except Exception as exc:  # noqa: BLE001 - 业务零影响：任何失败仅记录
        run.status = HrAgentRunStatus.FAILED
        run.error = str(exc)[:2000]
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["status", "error", "tool_trace", "duration_ms", "update_time"])
        write_audit_log(
            workspace_id, actor_id, "AGENT_RUN", "APPLICATION", application.id,
            result="FAILED", detail=f"screening agent failed: {str(exc)[:500]}", trace_id=run.id,
        )
        return _run_output(run, None)


def _write_skipped_run(workspace_id, actor_id, application, trigger_type, reason):
    run = HrAgentRun.objects.create(
        workspace_id=workspace_id,
        agent_type=_AGENT_TYPE,
        trigger_type=trigger_type,
        ref_object_type="APPLICATION",
        ref_object_id=str(application.id),
        status=HrAgentRunStatus.SKIPPED,
        input_meta={
            "application_id": str(application.id),
            "channel": application.channel,
            "stage_key": application.current_stage.key if application.current_stage else "",
        },
        error=reason,
        prompt_version=_PROMPT_VERSION,
        user_id=actor_id,
    )
    write_audit_log(
        workspace_id, actor_id, "AGENT_RUN", "APPLICATION", application.id,
        result="SKIPPED", detail=reason, trace_id=run.id,
    )
    return _run_output(run, None)


def _run_output(run, proposal):
    return {
        "run_id": str(run.id),
        "agent_type": run.agent_type,
        "status": run.status,
        "trigger_type": run.trigger_type,
        "error": run.error,
        "proposal_id": str(proposal.id) if proposal else None,
        "proposal_action": proposal.action if proposal else None,
        "duration_ms": run.duration_ms,
    }


def dispatch_event_screening(application_id):
    """事件触发分发（信号回调）：celery-once 防重；测试中可 patch。"""
    from hr.task.agent import run_screening_agent_task

    run_screening_agent_task.delay(application_id)
