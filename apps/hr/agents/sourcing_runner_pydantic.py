# coding=utf-8
"""
    @project: MaxKB
    @file： sourcing_runner_pydantic.py
    @date：2026/8/20
    @desc: Sourcing Agent Pydantic AI 迁移（Prompt 5）
"""
import json
import time
import uuid

from pydantic import BaseModel, Field

from common.exception.app_exception import AppApiException
from hr.agents import context
from hr.agents.pydantic_base import HrDeps, create_agent, get_pydantic_model, guard_limits, record_prompt_version, write_skipped_run
from hr.agents.proposals import expire_pending_proposals_for, propose
from hr.agents.scope import validate_resume_database_ids
from hr.models import Application, Candidate, HrAgentRun, HrAgentRunStatus, HrAgentTriggerType, HrAgentType, Job, JobStatus
from hr.services.audit import write_audit_log
from hr.services.resume_search import search_resumes

_SYSTEM_USER_ID = uuid.UUID(int=0)
_AGENT_TYPE = HrAgentType.SOURCING
_PROMPT_VERSION = "sourcing-v1"
_MAX_SEARCHES = 3
_MAX_CANDIDATES = 10

_SOURCING_PROMPT = """你是人才库激活助手，为职位 Y 从沉睡候选人池中筛选优先级激活清单。
输入：
<job>{job}</job>
<candidate_pool>{candidate_pool}</candidate_pool>

要求：
1. candidate_pool 已由系统做过硬条件核对与去重（已投递该职位的候选人已被剔除）；
   对每条候选人给出 匹配理由 / 主要风险 / 证据引用（evidence 必须来自提供的片段，不得编造）。
2. 只输出一个 JSON 对象（不要输出任何其他内容），结构如下：
{{
  "candidates": [
    {{
      "candidate_id": "候选人 id（必须来自输入）",
      "match_reason": "匹配理由（引用证据或结构化字段）",
      "risk": "主要风险（如年限不足/城市不符/最近项目偏差），没有则空字符串",
      "evidence": [{{"paragraph_id": "", "excerpt": "原文摘录（脱敏 chunk）", "relevance": 0.0}}]
    }}
  ],
  "summary": "一句话清单说明（覆盖范围与优先级口径）"
}}
3. candidates 至多 {max_candidates} 条，按匹配度降序；证据不足时明确标注，不得给出确定性结论。
4. 禁止以姓名/性别/年龄/婚育/民族/院校出身作为排序依据；不得编造候选人简历中不存在的内容。
5. 这是内部激活清单，不得包含任何外发话术。
"""


class Evidence(BaseModel):
    paragraph_id: str | None = None
    excerpt: str = Field(max_length=500)
    relevance: float = Field(ge=0, le=1)


class CandidateMatch(BaseModel):
    candidate_id: str = Field(description="候选人 id，必须来自输入")
    match_reason: str = Field(max_length=1000)
    risk: str = Field(max_length=500, default="")
    evidence: list[Evidence] = Field(default_factory=list)


class SourcingFacts(BaseModel):
    candidates: list[CandidateMatch] = Field(description="激活清单")
    summary: str = Field(max_length=1000)


def _config(workspace_id):
    from hr.models import HrConfig

    config = HrConfig.objects.filter(workspace_id=workspace_id).first()
    if config is None:
        config = HrConfig.objects.create(workspace_id=workspace_id, llm_model_id="")
    return config


def _sleeping_pool(workspace_id, job, search_items):
    applied = set(Application.objects.filter(workspace_id=workspace_id, job=job).values_list("candidate_id", flat=True))
    pool = []
    for item in (search_items or []):
        candidate = (item.get("candidate") or {})
        candidate_id = str(candidate.get("id") or "")
        if not candidate_id or candidate_id in applied:
            continue
        pool.append(item)
    return pool


def run_sourcing_agent(job_id, trigger_type=HrAgentTriggerType.MANUAL, user_id=None, workspace_id=None, data=None):
    job = Job.objects.filter(id=job_id).first()
    if job is None:
        return None
    if workspace_id is not None and str(job.workspace_id) != str(workspace_id):
        return None
    workspace_id = job.workspace_id
    data = data or {}
    resume_database_ids = validate_resume_database_ids(workspace_id, data.get("resume_database_ids") or data.get("resume_database_id"))
    actor_id = user_id or job.user_id or _SYSTEM_USER_ID
    config = _config(workspace_id)
    if job.status != JobStatus.OPEN:
        return write_skipped_run(workspace_id, actor_id, _AGENT_TYPE, trigger_type, "JOB", job.id, {"job_id": str(job.id), "job_name": job.name, "status": job.status}, _PROMPT_VERSION, "sourcing requires an OPEN job")
    skip_reason = guard_limits(workspace_id, config, _AGENT_TYPE)
    if skip_reason:
        return write_skipped_run(workspace_id, actor_id, _AGENT_TYPE, trigger_type, "JOB", job.id, {"job_id": str(job.id), "job_name": job.name}, _PROMPT_VERSION, skip_reason)

    expire_pending_proposals_for(workspace_id, "JOB", str(job.id))
    run = HrAgentRun.objects.create(
        workspace_id=workspace_id, agent_type=_AGENT_TYPE, trigger_type=trigger_type, ref_object_type="JOB", ref_object_id=str(job.id),
        status=HrAgentRunStatus.RUNNING, input_meta={"job_id": str(job.id), "job_name": job.name, "department": job.department, "resume_database_ids": resume_database_ids or []},
        prompt_version=_PROMPT_VERSION, user_id=actor_id,
    )
    started = time.monotonic()
    trace = []
    try:
        model, model_name = get_pydantic_model(workspace_id, config)
        if model is None:
            raise RuntimeError("LLM 模型未配置或不可用")
        t0 = time.monotonic()
        job_ctx = context.job_to_llm(job)
        trace.append({"tool": "get_job", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})
        queries = []
        if job.skill_requirements:
            queries.append(" ".join(job.skill_requirements))
        if job.name:
            queries.append(job.name)
        if job.description:
            queries.append(job.description[:200])
        recalled = []
        for query in queries[:_MAX_SEARCHES]:
            try:
                raw = search_resumes(workspace_id, query, top_k=8, mode="phrase", hr_role="VIEWER", user_id=None, llm_model=None, rerank_model=None, resume_database_ids=resume_database_ids)
            except AppApiException:
                continue
            recalled.extend(raw.get("items") or [])
        trace.append({"tool": "search_resumes", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(recalled)})
        t0 = time.monotonic()
        # 批量拉取候选人消除 N+1
        seen = set()
        candidate_ids = []
        for item in recalled:
            cid = str((item.get("candidate") or {}).get("id") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            candidate_ids.append(cid)
        candidate_map = {str(c.id): c for c in Candidate.objects.filter(id__in=candidate_ids, workspace_id=workspace_id)}
        from hr.agents.runner import structured_filter

        pool_items = []
        seen.clear()
        for item in recalled:
            cid = str((item.get("candidate") or {}).get("id") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            candidate = candidate_map.get(cid)
            if candidate is None:
                continue
            check = structured_filter(job, candidate)
            if not check["hard_met"]:
                continue
            pool_items.append(item)
        trace.append({"tool": "structured_filter", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(pool_items)})
        sleeping = _sleeping_pool(workspace_id, job, pool_items)
        if not sleeping:
            raise RuntimeError("no sleeping candidates after structured filter")
        allowed_ids = {str((item.get("candidate") or {}).get("id")) for item in sleeping}
        projected = context.search_to_llm({"items": sleeping, "meta": {}})
        prompt = _SOURCING_PROMPT.format(job=json.dumps(job_ctx, ensure_ascii=False), candidate_pool=json.dumps(projected, ensure_ascii=False), max_candidates=_MAX_CANDIDATES)

        deps = HrDeps(workspace_id=workspace_id, user_id=actor_id, job_id=str(job.id), job=job_ctx)
        agent = create_agent(model, deps_type=HrDeps, output_type=SourcingFacts, system_prompt=prompt)

        @agent.tool
        def get_job(ctx):
            return ctx.deps.job

        @agent.tool
        def search_resumes_tool(ctx, query: str):
            return {"items": projected["items"][:5]}

        result = agent.run_sync("请生成激活清单。", deps=deps)
        facts: SourcingFacts = result.output  # type: ignore
        # 校验 candidate_id 必须在 allowed_ids
        for row in facts.candidates:
            if row.candidate_id not in allowed_ids:
                raise ValueError(f"candidate_id not in pool: {row.candidate_id}")
        by_id = {str((item.get("candidate") or {}).get("id")): item for item in sleeping}
        candidates = []
        for row in facts.candidates[:_MAX_CANDIDATES]:
            item = by_id[row.candidate_id]
            candidate = item.get("candidate") or {}
            candidates.append({**row.model_dump(), "name": candidate.get("name"), "current_city": candidate.get("current_city"), "highest_degree": candidate.get("highest_degree"), "years_experience": candidate.get("years_experience"), "skills": candidate.get("skills"), "document_id": item.get("document_id")})
        payload = {"scope": {"job_id": str(job.id), "job_name": job.name}, "candidates": candidates, "summary": facts.summary}
        proposal = propose(workspace_id, run, str(job.id), action="DRAFT", payload_json=payload, target_type="JOB")
        run.output_json = payload
        run.status = HrAgentRunStatus.SUCCEEDED
        run.llm_model = model_name
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(result, "usage", lambda: {})() if hasattr(result, "usage") else {}
        try:
            prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        except Exception:
            prompt_tokens = 0
            completion_tokens = 0
        if not prompt_tokens and not completion_tokens:
            last = getattr(model, "_last_usage", {}) or {}
            prompt_tokens = int(last.get("input_tokens") or 0)
            completion_tokens = int(last.get("output_tokens") or 0)
        run.prompt_tokens = prompt_tokens
        run.completion_tokens = completion_tokens
        run.save(update_fields=["output_json", "status", "llm_model", "tool_trace", "duration_ms", "prompt_tokens", "completion_tokens", "update_time"])
        record_prompt_version(config, _AGENT_TYPE, _PROMPT_VERSION)
        write_audit_log(workspace_id, actor_id, "AGENT_RUN", "JOB", job.id, detail={"agent_type": _AGENT_TYPE, "trigger": trigger_type, "action": "DRAFT", "candidates": len(candidates)}, trace_id=run.id)
        from hr.agents.base import run_output

        return run_output(run, proposal)
    except Exception as exc:  # noqa: BLE001
        run.status = HrAgentRunStatus.FAILED
        run.error = str(exc)[:2000]
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["status", "error", "tool_trace", "duration_ms", "update_time"])
        write_audit_log(workspace_id, actor_id, "AGENT_RUN", "JOB", job.id, result="FAILED", detail=f"sourcing agent failed: {str(exc)[:500]}", trace_id=run.id)
        from hr.agents.base import run_output

        return run_output(run, None)
