# coding=utf-8
"""
    @project: MaxKB
    @file： copilot_runner_pydantic.py
    @date：2026/8/20
    @desc: Interview Copilot Pydantic AI 迁移（Prompt 4）：双 phase
"""
import json
import time
import uuid

from pydantic import BaseModel, Field

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed
from hr.agents import context
from hr.agents.pydantic_base import HrDeps, create_agent, get_pydantic_model, guard_limits, record_prompt_version, write_skipped_run
from hr.agents.proposals import expire_pending_proposals_for, propose
from hr.agents.scope import candidate_document_ids, validate_resume_database_ids
from hr.models import HrAgentRun, HrAgentRunStatus, HrAgentTriggerType, HrAgentType, Interview, InterviewStatus
from hr.services.audit import write_audit_log
from hr.services.knowledge_search import search_knowledge
from hr.services.resume_search import search_resumes
from hr.services.similar_jobs import similar_jobs

_SYSTEM_USER_ID = uuid.UUID(int=0)
_AGENT_TYPE = HrAgentType.INTERVIEW_COPILOT
_PROMPT_VERSION = "interview-copilot-v1"
_MAX_SEARCHES = 3

_PREPARE_PROMPT = """你是招聘面试助手，为一场面试生成结构化面试问题清单。
输入：
<job>{job}</job>
<candidate>{candidate}</candidate>
<weak_spots>{weak_spots}</weak_spots>
<question_bank>{question_bank}</question_bank>
<similar_jobs>{similar_jobs}</similar_jobs>

要求：
1. 依据职位硬/软要求与 <weak_spots>（候选人短板）设计问题，覆盖：技能深挖、经验真实性核对、软素质、动机。
2. 只输出一个 JSON 对象（不要输出任何其他内容），结构如下：
{{
  "weak_spots": [
    {{"name": "维度", "detail": "短板说明（必须引用证据或说明证据不足）",
      "evidence": [{{"paragraph_id": "", "excerpt": "原文摘录（脱敏 chunk）", "relevance": 0.0}}]}}
  ],
  "questions": [
    {{"question": "问题", "target": "考察点", "difficulty": "基础|进阶|深挖", "follow_up": "追问（可空）"}}
  ],
  "focus": ["面试重点1"]
}}
3. questions 至少 5 条、至多 12 条，难度梯度覆盖基础/进阶/深挖。
4. 可借鉴 <question_bank> 中的题目但不得照抄；禁止编造候选人简历中不存在的内容。
5. 禁止与性别/年龄/婚育/民族/院校出身相关的表述；问题面向技能与行为考察。
"""

_FEEDBACK_PROMPT = """你是招聘面试助手，基于面试官已提交反馈生成评估草稿（不自动提交，供人工参考）。
输入：
<job>{job}</job>
<candidate>{candidate}</candidate>
<interview_feedback>{interview_feedback}</interview_feedback>

要求：
1. 结合职位要求将面试官反馈整理为结构化评估草稿。
2. 只输出一个 JSON 对象（不要输出任何其他内容），结构如下：
{{
  "evaluation_draft": "结构化评估草稿（面试表现总结、与职位要求匹配度、强项、待核实点）",
  "recommendation_hint": "倾向建议（推进/待定/暂缓，仅供参考，决策由人）",
  "open_items": ["面试未覆盖、需要补充考察的点"]
}}
3. 只能基于给定反馈内容归纳，不得编造面试中未提及的内容。
"""


class Evidence(BaseModel):
    paragraph_id: str | None = None
    excerpt: str = Field(max_length=500)
    relevance: float = Field(ge=0, le=1)


class WeakSpot(BaseModel):
    name: str = Field(max_length=100)
    detail: str = Field(max_length=2000)
    evidence: list[Evidence] = Field(default_factory=list)


class Question(BaseModel):
    question: str = Field(max_length=2000)
    target: str = Field(max_length=500, default="")
    difficulty: str = Field(description="基础|进阶|深挖")
    follow_up: str = Field(max_length=2000, default="")

    @property
    def normalized_difficulty(self):
        return self.difficulty if self.difficulty in ("基础", "进阶", "深挖") else "进阶"


class PrepareFacts(BaseModel):
    weak_spots: list[WeakSpot] = Field(default_factory=list)
    questions: list[Question] = Field(description="5-12 条，覆盖基础/进阶/深挖")
    focus: list[str] = Field(default_factory=list)

    @property
    def validated_questions(self):
        # 保证 5-12 条，难度归一
        qs = []
        for q in self.questions:
            d = q.difficulty if q.difficulty in ("基础", "进阶", "深挖") else "进阶"
            qs.append(Question(question=q.question, target=q.target, difficulty=d, follow_up=q.follow_up))
        return qs[:12]


class FeedbackFacts(BaseModel):
    evaluation_draft: str = Field(max_length=8000)
    recommendation_hint: str = Field(max_length=500, default="")
    open_items: list[str] = Field(default_factory=list)


def _config(workspace_id):
    from hr.models import HrConfig

    config = HrConfig.objects.filter(workspace_id=workspace_id).first()
    if config is None:
        config = HrConfig.objects.create(workspace_id=workspace_id, llm_model_id="")
    return config


def _check_trigger_permission(interview, user_id, hr_role):
    if hr_role in ("OPERATOR", "ADMIN"):
        return
    if user_id and interview.interviewer_user_id and user_id == interview.interviewer_user_id:
        return
    write_audit_log(interview.workspace_id, user_id, "ACCESS_DENIED", "INTERVIEW", interview.id, result="DENIED", detail="Only the interviewer or operator+ can run the copilot")
    raise AppUnauthorizedFailed(403, "仅面试官本人或 OPERATOR 以上可运行 Interview Copilot")


def _candidate_document_ids(workspace_id, candidate_id, resume_database_ids=None):
    return candidate_document_ids(workspace_id, candidate_id, resume_database_ids)


def _collect_weak_spots(workspace_id, application, document_ids, resume_database_ids=None):
    job = application.job
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
                workspace_id, query, top_k=5, mode="phrase", hr_role="VIEWER", user_id=None, llm_model=None, rerank_model=None,
                candidate_id=str(application.candidate_id), document_ids=document_ids, resume_database_ids=resume_database_ids,
            )
        except AppApiException:
            continue
        projected = context.search_to_llm(raw)
        results.append({"query": query[:100], **projected})
    return results


def _collect_question_bank(workspace_id, job):
    queries = []
    if job.name:
        queries.append(f"{job.name} 面试题")
    if job.skill_requirements:
        queries.append(" ".join(job.skill_requirements) + " 面试 考察")
    hits = []
    for query in queries[:_MAX_SEARCHES]:
        try:
            raw = search_knowledge(workspace_id, query, top_k=5)
        except AppApiException:
            continue
        projected = context.knowledge_to_llm(raw)
        if projected["items"]:
            hits.append({"query": query[:100], **projected})
    return hits


def run_interview_copilot(interview_id, data=None, user_id=None, hr_role=None, workspace_id=None):
    interview = Interview.objects.filter(id=interview_id).select_related("application__candidate", "application__job").first()
    if interview is None or interview.application is None:
        return None
    if workspace_id is not None and str(interview.workspace_id) != str(workspace_id):
        return None
    application = interview.application
    workspace_id = interview.workspace_id
    actor_id = user_id or interview.user_id or _SYSTEM_USER_ID
    _check_trigger_permission(interview, user_id, hr_role)
    config = _config(workspace_id)

    data = data or {}
    resume_database_ids = validate_resume_database_ids(workspace_id, data.get("resume_database_ids") or data.get("resume_database_id"))
    phase = str(data.get("phase") or "prepare").strip()
    if phase not in ("prepare", "feedback"):
        return write_skipped_run(workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "INTERVIEW", interview.id, {"interview_id": str(interview.id), "application_id": str(application.id), "phase": phase}, _PROMPT_VERSION, "invalid phase")
    feedback = str(data.get("feedback") or "").strip()[:8000]
    if phase == "feedback" and not feedback:
        return write_skipped_run(workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "INTERVIEW", interview.id, {"interview_id": str(interview.id), "application_id": str(application.id), "phase": phase}, _PROMPT_VERSION, "feedback text required for feedback phase")
    if phase == "prepare" and interview.status != InterviewStatus.PENDING:
        return write_skipped_run(workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "INTERVIEW", interview.id, {"interview_id": str(interview.id), "application_id": str(application.id), "phase": phase, "status": interview.status}, _PROMPT_VERSION, "interview not pending")
    skip_reason = guard_limits(workspace_id, config, _AGENT_TYPE)
    if skip_reason:
        return write_skipped_run(workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "INTERVIEW", interview.id, {"interview_id": str(interview.id), "phase": phase}, _PROMPT_VERSION, skip_reason)

    expire_pending_proposals_for(workspace_id, "INTERVIEW", str(interview.id))
    run = HrAgentRun.objects.create(
        workspace_id=workspace_id, agent_type=_AGENT_TYPE, trigger_type=HrAgentTriggerType.MANUAL, ref_object_type="INTERVIEW", ref_object_id=str(interview.id),
        status=HrAgentRunStatus.RUNNING, input_meta={"interview_id": str(interview.id), "application_id": str(application.id), "job_id": str(application.job_id), "candidate_id": str(application.candidate_id), "phase": phase, "round_no": interview.round_no, "resume_database_ids": resume_database_ids or []},
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

        prompt_kwargs = {"job": json.dumps(job_ctx, ensure_ascii=False), "candidate": json.dumps(candidate_ctx, ensure_ascii=False)}
        if phase == "prepare":
            t0 = time.monotonic()
            document_ids = _candidate_document_ids(workspace_id, application.candidate_id, resume_database_ids)
            weak_spots = _collect_weak_spots(workspace_id, application, document_ids, resume_database_ids)
            trace.append({"tool": "search_resumes", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(weak_spots)})
            t0 = time.monotonic()
            question_bank = _collect_question_bank(workspace_id, application.job)
            trace.append({"tool": "search_knowledge", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(question_bank)})
            t0 = time.monotonic()
            try:
                similar_ctx = context.similar_jobs_to_llm(similar_jobs(workspace_id, str(application.job_id)))
            except AppApiException:
                similar_ctx = []
            trace.append({"tool": "similar_jobs", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": len(similar_ctx)})
            prompt = _PREPARE_PROMPT.format(**prompt_kwargs, weak_spots=json.dumps(weak_spots, ensure_ascii=False), question_bank=json.dumps(question_bank, ensure_ascii=False), similar_jobs=json.dumps(similar_ctx, ensure_ascii=False))
            deps = HrDeps(workspace_id=workspace_id, user_id=actor_id, hr_role=hr_role, interview_id=str(interview.id), job_id=str(application.job_id), application_id=str(application.id))
            agent = create_agent(model, deps_type=HrDeps, output_type=PrepareFacts, system_prompt=prompt)

            @agent.tool
            def get_job(ctx):
                return ctx.deps.job if ctx.deps.job else job_ctx

            @agent.tool
            def search_resumes_tool(ctx, query: str):
                return {"items": weak_spots[:5]}

            @agent.tool
            def search_knowledge_tool(ctx, query: str):
                return {"items": question_bank[:5]}

            result = agent.run_sync("请生成面试准备材料。", deps=deps)
            facts: PrepareFacts = result.output  # type: ignore
            # 校验 questions 数量
            if len(facts.questions) < 5:
                raise ValueError("questions must be at least 5")
            payload = {"phase": phase, "weak_spots": [w.model_dump() for w in facts.weak_spots], "questions": [q.model_dump() for q in facts.questions[:12]], "focus": facts.focus}
        else:
            prompt = _FEEDBACK_PROMPT.format(**prompt_kwargs, interview_feedback=json.dumps(feedback, ensure_ascii=False))
            deps = HrDeps(workspace_id=workspace_id, user_id=actor_id, hr_role=hr_role, interview_id=str(interview.id))
            agent = create_agent(model, deps_type=HrDeps, output_type=FeedbackFacts, system_prompt=prompt)

            @agent.tool
            def get_job(ctx):
                return job_ctx

            @agent.tool
            def get_candidate(ctx):
                return candidate_ctx

            result = agent.run_sync("请基于反馈生成评估草稿。", deps=deps)
            facts: FeedbackFacts = result.output  # type: ignore
            payload = {"phase": phase, "evaluation_draft": facts.evaluation_draft, "recommendation_hint": facts.recommendation_hint, "open_items": facts.open_items}

        proposal = propose(workspace_id, run, str(interview.id), action="DRAFT", payload_json=payload, target_type="INTERVIEW")
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
        write_audit_log(workspace_id, actor_id, "AGENT_RUN", "INTERVIEW", interview.id, detail={"agent_type": _AGENT_TYPE, "trigger": "MANUAL", "action": "DRAFT", "phase": phase}, trace_id=run.id)
        from hr.agents.base import run_output

        return run_output(run, proposal)
    except Exception as exc:  # noqa: BLE001
        run.status = HrAgentRunStatus.FAILED
        run.error = str(exc)[:2000]
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["status", "error", "tool_trace", "duration_ms", "update_time"])
        write_audit_log(workspace_id, actor_id, "AGENT_RUN", "INTERVIEW", interview.id, result="FAILED", detail=f"interview copilot failed: {str(exc)[:500]}", trace_id=run.id)
        from hr.agents.base import run_output

        return run_output(run, None)
