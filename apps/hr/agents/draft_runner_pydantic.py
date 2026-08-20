# coding=utf-8
"""
    @project: MaxKB
    @file： draft_runner_pydantic.py
    @date：2026/8/20
    @desc: 沟通草稿助手 Pydantic AI 迁移（Prompt 6）
"""
import json
import time
import uuid

from pydantic import BaseModel, Field

from common.exception.app_exception import AppApiException
from hr.agents import context
from hr.agents.pydantic_base import HrDeps, create_agent, get_pydantic_model, guard_limits, record_prompt_version, write_skipped_run
from hr.agents.proposals import expire_pending_proposals, propose
from hr.models import Application, HrAgentRun, HrAgentRunStatus, HrAgentTriggerType, HrAgentType
from hr.services.audit import write_audit_log
from hr.services.knowledge_search import search_knowledge

_SYSTEM_USER_ID = uuid.UUID(int=0)
_AGENT_TYPE = HrAgentType.COMMUNICATION_DRAFT
_PROMPT_VERSION = "communication-draft-v1"
_SCENARIOS = ("REJECT", "PROGRESS", "FAQ", "OTHER")
_MAX_SEARCHES = 3

_DRAFT_PROMPT = """你是招聘沟通草稿助手，为候选人沟通生成外发话术草稿。
输入：
<scenario>{scenario}</scenario>
<job>{job}</job>
<candidate>{candidate}</candidate>
<context_note>{context_note}</context_note>
<knowledge_hits>{knowledge_hits}</knowledge_hits>

要求：
1. scenario 含义：REJECT=婉拒/淘汰通知；PROGRESS=进度同步（如进入下一轮/补充材料）；FAQ=答疑（结合 context_note 中的候选人问题）；OTHER=其他沟通。
2. 以 <knowledge_hits> 中的企业话术/FAQ/政策为素材（要点借鉴，不整段复制）；语气专业、克制、符合公司口径。
3. 只输出一个 JSON 对象（不要输出任何其他内容），结构如下：
{{
  "draft": "完整话术草稿（Markdown，含称呼占位 {{候选人}} 与可编辑空位），不能包含联系方式以外的任何敏感信息",
  "key_points": ["话术要点1"],
  "tone": "语气与边界说明",
  "sources": [{{"kind": "knowledge", "ref": "来源标识", "note": "借鉴点"}}]
}}
4. 禁止在草稿中承诺未确认的结果（如面试结果/Offer）；涉及数据/政策引用必须来自知识库素材，不得编造。
5. 草稿不发送，仅由 HR 人工审核后外发。
"""


class Source(BaseModel):
    kind: str = Field(max_length=20)
    ref: str = Field(max_length=200)
    note: str = Field(max_length=500)


class CommunicationFacts(BaseModel):
    draft: str = Field(max_length=8000, description="完整话术草稿 Markdown")
    key_points: list[str] = Field(default_factory=list)
    tone: str = Field(max_length=500, default="")
    sources: list[Source] = Field(default_factory=list)


def _config(workspace_id):
    from hr.models import HrConfig

    config = HrConfig.objects.filter(workspace_id=workspace_id).first()
    if config is None:
        config = HrConfig.objects.create(workspace_id=workspace_id, llm_model_id="")
    return config


def _scenario_label(scenario):
    return {"REJECT": "婉拒/淘汰通知", "PROGRESS": "进度通知", "FAQ": "答疑", "OTHER": "其他沟通"}.get(scenario, scenario)


def _collect_knowledge(workspace_id, scenario, job, context_note):
    queries = []
    if scenario == "FAQ" and context_note:
        queries.append(context_note[:100])
    queries.append(_scenario_label(scenario) + " 话术")
    if job.skill_requirements:
        queries.append(" ".join(job.skill_requirements)[:100])
    hits = []
    for query in queries[:_MAX_SEARCHES]:
        try:
            raw = search_knowledge(workspace_id, query, top_k=4)
        except AppApiException:
            continue
        projected = context.knowledge_to_llm(raw)
        if projected["items"]:
            hits.append({"query": query[:100], **projected})
    return hits


def run_communication_draft(application_id, data=None, user_id=None, hr_role=None, workspace_id=None):
    application = Application.objects.filter(id=application_id).select_related("candidate", "job").first()
    if application is None:
        return None
    if workspace_id is not None and str(application.workspace_id) != str(workspace_id):
        return None
    workspace_id = application.workspace_id
    actor_id = user_id or application.user_id or _SYSTEM_USER_ID
    config = _config(workspace_id)

    data = data or {}
    scenario = str(data.get("scenario") or "OTHER").strip().upper()
    if scenario not in _SCENARIOS:
        return write_skipped_run(workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "APPLICATION", application.id, {"application_id": str(application.id), "scenario": scenario}, _PROMPT_VERSION, "invalid scenario")
    context_note = str(data.get("context_note") or "").strip()[:1000]
    skip_reason = guard_limits(workspace_id, config, _AGENT_TYPE)
    if skip_reason:
        return write_skipped_run(workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "APPLICATION", application.id, {"application_id": str(application.id), "scenario": scenario}, _PROMPT_VERSION, skip_reason)

    expire_pending_proposals(workspace_id, application_id)
    run = HrAgentRun.objects.create(
        workspace_id=workspace_id, agent_type=_AGENT_TYPE, trigger_type=HrAgentTriggerType.MANUAL, ref_object_type="APPLICATION", ref_object_id=str(application.id),
        status=HrAgentRunStatus.RUNNING, input_meta={"application_id": str(application.id), "job_id": str(application.job_id), "candidate_id": str(application.candidate_id), "scenario": scenario, "stage_key": application.current_stage.key if application.current_stage else ""},
        prompt_version=_PROMPT_VERSION, user_id=actor_id,
    )
    started = time.monotonic()
    trace = []
    try:
        model, model_name = get_pydantic_model(workspace_id, config)
        if model is None:
            raise RuntimeError("LLM 模型未配置或不可用")
        t0 = time.monotonic()
        job_ctx = context.job_to_llm(application.job)
        trace.append({"tool": "get_job", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})
        t0 = time.monotonic()
        candidate_ctx = context.candidate_to_llm(application.candidate)
        trace.append({"tool": "get_candidate_overview", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})
        t0 = time.monotonic()
        knowledge_hits = _collect_knowledge(workspace_id, scenario, application.job, context_note)
        trace.append({"tool": "search_knowledge", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(knowledge_hits)})

        prompt = _DRAFT_PROMPT.format(scenario=json.dumps(_scenario_label(scenario), ensure_ascii=False), job=json.dumps(job_ctx, ensure_ascii=False), candidate=json.dumps(candidate_ctx, ensure_ascii=False), context_note=json.dumps(context_note or "（无）", ensure_ascii=False), knowledge_hits=json.dumps(knowledge_hits, ensure_ascii=False))

        deps = HrDeps(workspace_id=workspace_id, user_id=actor_id, hr_role=hr_role, application_id=str(application.id))
        agent = create_agent(model, deps_type=HrDeps, output_type=CommunicationFacts, system_prompt=prompt)

        @agent.tool
        def get_job(ctx):
            return ctx.deps.job if hasattr(ctx.deps, "job") and ctx.deps.job else job_ctx

        @agent.tool
        def get_candidate_overview(ctx):
            return candidate_ctx

        @agent.tool
        def search_knowledge_tool(ctx, query: str):
            return {"items": knowledge_hits[:5]}

        result = agent.run_sync("请生成沟通草稿。", deps=deps)
        facts: CommunicationFacts = result.output  # type: ignore

        payload = {"scenario": scenario, "stage_key": application.current_stage.key if application.current_stage else "", "draft": facts.draft, "key_points": facts.key_points, "tone": facts.tone, "sources": [s.model_dump() for s in facts.sources]}
        proposal = propose(workspace_id, run, str(application.id), action="DRAFT", payload_json=payload)
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
        write_audit_log(workspace_id, actor_id, "AGENT_RUN", "APPLICATION", application.id, detail={"agent_type": _AGENT_TYPE, "trigger": "MANUAL", "action": "DRAFT", "scenario": scenario}, trace_id=run.id)
        from hr.agents.base import run_output

        return run_output(run, proposal)
    except Exception as exc:  # noqa: BLE001
        run.status = HrAgentRunStatus.FAILED
        run.error = str(exc)[:2000]
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["status", "error", "tool_trace", "duration_ms", "update_time"])
        write_audit_log(workspace_id, actor_id, "AGENT_RUN", "APPLICATION", application.id, result="FAILED", detail=f"communication draft failed: {str(exc)[:500]}", trace_id=run.id)
        from hr.agents.base import run_output

        return run_output(run, None)
