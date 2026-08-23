# coding=utf-8
"""
    @project: MaxKB
    @file： runner_pydantic.py
    @date：2026/8/20
    @desc: Screening Agent Pydantic AI 标杆迁移（Prompt 2）：
           同签名 run_screening_agent(...), 单次 Agent.run_sync, Pydantic BaseModel 校验，
           禁止 ReAct 循环，保留账本/护栏/评分。
"""
import json
import time
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_ai import ModelRetry, capture_run_messages

from common.exception.app_exception import AppApiException
from hr.agents import context, scoring
from hr.agents.pydantic_base import HrDeps, create_agent, get_pydantic_model, guard_limits, record_prompt_version
from hr.agents.proposals import expire_pending_proposals, propose
from hr.agents.scope import candidate_document_ids, validate_resume_database_ids
from hr.models import Application, ApplicationStatus, HrAgentRun, HrAgentRunStatus, HrAgentTriggerType, RelationType
from hr.services.audit import write_audit_log
from hr.services.resume_search import search_resumes

import contextvars

# 并发隔离：每 run 的允许 paragraph_id 集合存于 ContextVar，避免全局 set 互相污染（P2-7）
_allowed_ids_ctx: contextvars.ContextVar[set[str]] = contextvars.ContextVar("_allowed_ids_ctx", default=set())

_SYSTEM_USER_ID = uuid.UUID(int=0)
_PROMPT_VERSION = "screening-v2"
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
8. relevance 与 confidence 反映「实质语义支撑强度」（0~1）：
   - 0.7~1.0：该片段实质支撑维度结论（技能/职责/经验直接对应，即使表述用词不同）；
   - 0.4~0.7：部分支撑；<0.4：弱相关或无关。
   不得因为候选简历存在字段矛盾、时间线异常、模板化表述等「格式疑点」而压低相关性数值——
   这类疑虑请写入 concerns，由人工复核，不影响 relevance/confidence 的语义评估。
9. confidence 表示你对维度结论的确信程度；结论有被引用证据实质支撑时，不应因候选其它经历不相关而压低当前维度置信度。
"""

# 兼容旧全局（已迁移至 ContextVar，保留空集避免旧代码引用报错）
_ALLOWED_PARAGRAPH_IDS: set[str] = set()

DIMENSION_WHITELIST = ("技能匹配", "经验相关性", "工作年限", "城市", "学历")


class Evidence(BaseModel):
    paragraph_id: str | None = Field(default=None, description="段落 ID，必须来自检索结果")
    excerpt: str = Field(max_length=500, description="原文摘录（脱敏 chunk）")
    relevance: float = Field(ge=0, le=1, description="相关性 0-1，实质语义支撑强度")


class DimensionFact(BaseModel):
    name: str = Field(description="维度名，只能取技能匹配、经验相关性、工作年限、城市、学历之一")
    verdict: str = Field(description="该维度的评估结论（必须引用证据或说明证据不足）")
    evidence: list[Evidence] = Field(default_factory=list, description="支撑证据，需摘录原文")
    confidence: float = Field(ge=0, le=1, description="置信度 0-1")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = str(v).strip()
        if v not in DIMENSION_WHITELIST:
            raise ValueError(f"维度名必须为白名单之一: {DIMENSION_WHITELIST}")
        return v


class ScreeningFacts(BaseModel):
    dimensions: list[DimensionFact] = Field(description="维度评估，需白名单")
    concerns: list[str] = Field(default_factory=list, description="风险点")
    clarifying_questions: list[str] = Field(default_factory=list, description="需澄清的问题")

    @field_validator("dimensions")
    @classmethod
    def _validate_dimensions(cls, v):
        if not isinstance(v, list) or not v:
            raise ValueError("dimensions must be a non-empty list")
        return v

    @model_validator(mode="after")
    def _validate_evidence_ids(self):
        # Evidence.paragraph_id 必须来自本次检索结果，防止编造证据（P2-7：改 ContextVar 隔离）
        allowed = _allowed_ids_ctx.get()
        if allowed:
            for dim in self.dimensions:
                for ev in dim.evidence:
                    pid = ev.paragraph_id
                    if pid is not None and str(pid) not in allowed:
                        raise ModelRetry(f"evidence paragraph_id not in retrieved set: {pid}")
        return self


def _config(workspace_id):
    from hr.models import HrConfig

    config = HrConfig.objects.filter(workspace_id=workspace_id).first()
    if config is None:
        config = HrConfig.objects.create(workspace_id=workspace_id, llm_model_id="")
    return config


def _load_llm(workspace_id, config):
    # 复用 pydantic_base 的获取，保持与原 runner 一致的模型解析
    return get_pydantic_model(workspace_id, config)


def structured_filter(job, candidate):
    """复用原 runner 的硬条件核对（保持 100% 一致）"""
    from hr.agents.runner import structured_filter as _orig

    return _orig(job, candidate)


def _collect_evidence(workspace_id, job, candidate, document_ids, resume_database_ids=None):
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
                resume_database_ids=resume_database_ids,
            )
        except AppApiException:
            continue
        projected = context.search_to_llm(raw)
        results.append({"query": query, "items": projected["items"], "meta": projected["meta"]})
    return results


def _allowed_paragraph_ids(results):
    ids = set()
    for result in results:
        for item in result.get("items", []):
            for paragraph in item.get("paragraphs", []):
                paragraph_id = paragraph.get("paragraph_id") or paragraph.get("id")
                if paragraph_id:
                    ids.add(str(paragraph_id))
    return ids


def run_screening_agent(application_id, trigger_type=HrAgentTriggerType.EVENT, user_id=None, workspace_id=None, resume_database_ids=None):
    """同签名 run_screening_agent，Pydantic AI 单次 run_sync 实现"""
    application = Application.objects.filter(id=application_id).select_related("candidate", "job", "current_stage").first()
    if application is None:
        return None
    if workspace_id is not None and str(application.workspace_id) != str(workspace_id):
        return None
    workspace_id = application.workspace_id
    resume_database_ids = validate_resume_database_ids(workspace_id, resume_database_ids)
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

    skip_reason = guard_limits(workspace_id, config, _AGENT_TYPE)
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
            "resume_database_ids": resume_database_ids or [],
        },
        prompt_version=_PROMPT_VERSION,
        user_id=actor_id,
    )
    started = time.monotonic()
    trace = []
    prompt_tokens = 0  # 全部 LLM 请求（含校验重试）的 token 累计；SUCCEEDED/FAILED 均落库
    completion_tokens = 0
    run_messages: list = []  # capture_run_messages 捕获的消息：run 失败时仍可读取已发生请求的用量
    _token = _allowed_ids_ctx.set(set())
    try:
        model, model_name = _load_llm(workspace_id, config)
        if model is None:
            raise RuntimeError("LLM model is not configured or unavailable")

        # 工具数据预取（用于 deps 与 prompt 构造，保持与原 runner 的固定顺序工具调用语义）
        t0 = time.monotonic()
        job_ctx = context.job_to_llm(application.job)
        trace.append({"tool": "get_job", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})
        t0 = time.monotonic()
        candidate_ctx = context.candidate_to_llm(application.candidate)
        trace.append({"tool": "get_candidate_overview", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})
        t0 = time.monotonic()
        filter_result = structured_filter(application.job, application.candidate)
        filter_ctx = context.structured_filter_to_llm(filter_result)
        trace.append({"tool": "structured_filter", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(filter_result["conditions"])})
        document_ids = candidate_document_ids(workspace_id, application.candidate_id, resume_database_ids)
        t0 = time.monotonic()
        evidence = _collect_evidence(workspace_id, application.job, application.candidate, document_ids, resume_database_ids)
        allowed_paragraph_ids = _allowed_paragraph_ids(evidence)
        _allowed_ids_ctx.set(allowed_paragraph_ids)
        trace.append({"tool": "search_resumes", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(evidence)})

        prompt = _SCREENING_PROMPT.format(
            job=json.dumps(job_ctx, ensure_ascii=False),
            candidate=json.dumps(candidate_ctx, ensure_ascii=False),
            hard_conditions=json.dumps(filter_ctx, ensure_ascii=False),
            evidence=json.dumps(evidence, ensure_ascii=False),
        )

        # 创建 Pydantic AI Agent，注册工具（工具内仅返回已脱敏数据，保持 100% 脱敏投影）
        deps = HrDeps(
            workspace_id=workspace_id,
            user_id=actor_id,
            hr_role=None,
            application_id=str(application.id),
            job_id=str(application.job_id),
            application=job_ctx,  # 复用 job_ctx 作为占位，实际工具内会重新取
            job=job_ctx,
        )
        # 为工具闭包捕获 evidence 等，定义 agent
        agent = create_agent(model, deps_type=HrDeps, output_type=ScreeningFacts, system_prompt=prompt)

        @agent.tool
        def get_job(ctx):
            return ctx.deps.job

        @agent.tool
        def get_candidate_overview(ctx):
            # 脱敏候选人概览
            return candidate_ctx

        @agent.tool
        def search_resumes_tool(ctx, query: str):
            # 透传限集检索（已脱敏）
            # query 参数由 LLM 决定，但我们固定返回预取的 evidence 对应 query 的子集，保持与原 runner 的 phrase 检索一致
            # 为简化，直接返回全部 evidence（已脱敏）
            return {"items": evidence, "allowed_ids": list(allowed_paragraph_ids)}

        # 单次 run_sync，无 ReAct 循环；capture_run_messages 保证中途抛错时已发生请求的消息（含用量）仍可读
        with capture_run_messages() as run_messages:
            result = agent.run_sync("请基于给定证据完成人岗匹配评估，严格按白名单维度输出。", deps=deps)
        facts: ScreeningFacts = result.output  # type: ignore
        # 清理
        _allowed_ids_ctx.set(set())

        # 空检索分支：无证据 → HOLD
        evidence_available = any(item.get("items") for item in evidence)
        if evidence_available:
            decision = scoring.derive_decision(
                facts.model_dump(), filter_result["hard_met"], bands=config.agent_score_bands or {}, score_version=config.agent_score_version or "v1"
            )
        else:
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
            "dimensions": [d.model_dump() for d in facts.dimensions],
            "concerns": facts.concerns,
            "clarifying_questions": facts.clarifying_questions,
            "decision": decision,
        }
        proposal = propose(workspace_id, run, target_id=str(application.id), action=payload["decision"]["suggested_action"], payload_json=payload)
        run.output_json = payload
        run.status = HrAgentRunStatus.SUCCEEDED
        run.llm_model = model_name
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(result, "usage", lambda: {})() if hasattr(result, "usage") else {}
        # Pydantic AI usage 可能为 Usage 对象
        try:
            prompt_tokens = int(getattr(usage, "input_tokens", 0) or getattr(usage, "request_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "output_tokens", 0) or getattr(usage, "response_tokens", 0) or 0)
        except Exception:
            prompt_tokens = 0
            completion_tokens = 0
        # 兼容旧 _last_usage
        if not prompt_tokens and not completion_tokens:
            last = getattr(model, "_last_usage", {}) or {}
            prompt_tokens = int(last.get("input_tokens") or last.get("prompt_tokens") or 0)
            completion_tokens = int(last.get("output_tokens") or last.get("completion_tokens") or 0)
        run.prompt_tokens = prompt_tokens
        run.completion_tokens = completion_tokens
        run.save(update_fields=["output_json", "status", "llm_model", "tool_trace", "duration_ms", "prompt_tokens", "completion_tokens", "update_time"])
        record_prompt_version(config, _AGENT_TYPE, _PROMPT_VERSION)
        write_audit_log(
            workspace_id, actor_id, "AGENT_RUN", "APPLICATION", application.id,
            detail={"agent_type": _AGENT_TYPE, "trigger": trigger_type, "action": payload["decision"]["suggested_action"], "score": payload["decision"]["score"]},
            trace_id=run.id,
        )
        _allowed_ids_ctx.reset(_token)
        return _run_output(run, proposal)
    except Exception as exc:  # noqa: BLE001
        try:
            _allowed_ids_ctx.set(set())
        except Exception:
            pass
        if not prompt_tokens and not completion_tokens:
            # P2 成本核算修复：FAILED 也落库已发生的 token——从捕获消息累加每次请求的用量（含校验重试触发的额外请求）
            for message in run_messages:
                request_usage = getattr(message, "usage", None)
                if request_usage is None:
                    continue
                try:
                    prompt_tokens += int(getattr(request_usage, "input_tokens", 0) or 0)
                    completion_tokens += int(getattr(request_usage, "output_tokens", 0) or 0)
                except Exception:
                    pass
        run.status = HrAgentRunStatus.FAILED
        run.error = str(exc)[:2000]
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.prompt_tokens = prompt_tokens
        run.completion_tokens = completion_tokens
        run.save(update_fields=["status", "error", "tool_trace", "duration_ms", "prompt_tokens", "completion_tokens", "update_time"])
        write_audit_log(workspace_id, actor_id, "AGENT_RUN", "APPLICATION", application.id, result="FAILED", detail=f"screening agent failed: {str(exc)[:500]}", trace_id=run.id)
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
    write_audit_log(workspace_id, actor_id, "AGENT_RUN", "APPLICATION", application.id, result="SKIPPED", detail=reason, trace_id=run.id)
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
    from hr.task.agent import run_screening_agent_task

    run_screening_agent_task.delay(application_id)
