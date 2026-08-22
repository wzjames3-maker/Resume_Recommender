# coding=utf-8
"""
    @project: MaxKB
    @file： copilot_runner.py
    @date：2026/8/17
    @desc: Interview Copilot Agent（PRD-AGENT-RAG §5 Agent 清单，D2）：
           面试创建后/面试前人工触发（本人面试官或 OPERATOR+）。
           prepare：按简历弱项 + JD + 企业题库生成结构化面试问题；
           feedback：按面试官已提交反馈生成评估草稿（不自动提交）。
           产物均为 DRAFT 提案，不改任何业务状态；面试反馈永远人工提交。
"""
import json
import time
import uuid

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed
from hr.agents import context
from hr.agents.base import guard_limits, record_prompt_version, run_output, write_skipped_run
from hr.agents.proposals import expire_pending_proposals_for, propose
from hr.agents.runner import _allowed_paragraph_ids, _config, _invoke_llm, _is_number, _load_llm
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


def _validate_prepare_facts(data, allowed_paragraph_ids=None):
    if not isinstance(data, dict):
        raise ValueError("facts must be an object")
    weak_spots = []
    for item in (data.get("weak_spots") or []):
        if not isinstance(item, dict):
            continue
        evidence = []
        for entry in (item.get("evidence") or []):
            if isinstance(entry, dict):
                paragraph_id = entry.get("paragraph_id")
                # evidence paragraph_id 必须来自本次检索结果，防止编造证据（P2-8）
                if allowed_paragraph_ids is not None and str(paragraph_id or "") not in allowed_paragraph_ids:
                    raise ValueError(f"evidence paragraph_id not in retrieved set: {paragraph_id}")
                evidence.append({
                    "paragraph_id": paragraph_id,
                    "excerpt": str(entry.get("excerpt") or "")[:500],
                    "relevance": float(entry.get("relevance", 0) or 0) if _is_number(entry.get("relevance")) else 0.0,
                })
        weak_spots.append({
            "name": str(item.get("name") or "")[:100],
            "detail": str(item.get("detail") or "")[:2000],
            "evidence": evidence,
        })
    questions = []
    for item in (data.get("questions") or []):
        if not isinstance(item, dict) or not str(item.get("question") or "").strip():
            continue
        difficulty = str(item.get("difficulty") or "")
        if difficulty not in ("基础", "进阶", "深挖"):
            difficulty = "进阶"
        questions.append({
            "question": str(item["question"]).strip()[:2000],
            "target": str(item.get("target") or "")[:500],
            "difficulty": difficulty,
            "follow_up": str(item.get("follow_up") or "")[:2000],
        })
    if not questions:
        raise ValueError("questions must be a non-empty list")
    return {
        "weak_spots": weak_spots,
        "questions": questions[:12],
        "focus": [str(item)[:200] for item in (data.get("focus") or []) if isinstance(item, str)][:10],
    }


def _validate_feedback_facts(data, allowed_paragraph_ids=None):
    """feedback 阶段无 evidence，allowed_paragraph_ids 仅保持与 prepare 校验器同签名。"""
    if not isinstance(data, dict):
        raise ValueError("facts must be an object")
    draft = str(data.get("evaluation_draft") or "").strip()
    if not draft:
        raise ValueError("evaluation_draft is required")
    return {
        "evaluation_draft": draft[:8000],
        "recommendation_hint": str(data.get("recommendation_hint") or "").strip()[:500],
        "open_items": [str(item)[:500] for item in (data.get("open_items") or []) if isinstance(item, str)][:10],
    }


def _check_trigger_permission(interview, user_id, hr_role):
    """本人面试官或 OPERATOR+ 可触发 Copilot；VIEWER 只见脱敏数据（§9/A3）。"""
    if hr_role in ("OPERATOR", "ADMIN"):
        return
    if user_id and interview.interviewer_user_id and user_id == interview.interviewer_user_id:
        return
    write_audit_log(
        interview.workspace_id, user_id, "ACCESS_DENIED", "INTERVIEW", interview.id,
        result="DENIED", detail="Only the interviewer or operator+ can run the copilot",
    )
    raise AppUnauthorizedFailed(403, "仅面试官本人或 OPERATOR 以上可运行 Interview Copilot")


def _candidate_document_ids(workspace_id, candidate_id, resume_database_ids=None):
    return candidate_document_ids(workspace_id, candidate_id, resume_database_ids)


def _collect_weak_spots(workspace_id, application, document_ids, resume_database_ids=None):
    """候选人文档集内软条件语义检索（复用 RRF+rerank，召回入口限集）。"""
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
                workspace_id,
                query,
                top_k=5,
                mode="phrase",
                hr_role="VIEWER",
                user_id=None,
                llm_model=None,
                rerank_model=None,
                candidate_id=str(application.candidate_id),
                document_ids=document_ids,
                resume_database_ids=resume_database_ids,
            )
        except AppApiException:
            continue
        projected = context.search_to_llm(raw)
        results.append({"query": query[:100], **projected})
    return results


def _collect_question_bank(workspace_id, job):
    """企业题库检索（白名单）。"""
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
    """执行一次 Interview Copilot 运行；任何失败 run=FAILED，面试流程不受影响。
    workspace_id 由 API 传入时强制校验归属。"""
    interview = (
        Interview.objects.filter(id=interview_id)
        .select_related("application__candidate", "application__job")
        .first()
    )
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
    resume_database_ids = validate_resume_database_ids(
        workspace_id, data.get("resume_database_ids") or data.get("resume_database_id")
    )
    phase = str(data.get("phase") or "prepare").strip()
    if phase not in ("prepare", "feedback"):
        return write_skipped_run(
            workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "INTERVIEW", interview.id,
            {"interview_id": str(interview.id), "application_id": str(application.id), "phase": phase},
            _PROMPT_VERSION, "invalid phase",
        )
    feedback = str(data.get("feedback") or "").strip()[:8000]
    if phase == "feedback" and not feedback:
        return write_skipped_run(
            workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "INTERVIEW", interview.id,
            {"interview_id": str(interview.id), "application_id": str(application.id), "phase": phase},
            _PROMPT_VERSION, "feedback text required for feedback phase",
        )
    if phase == "prepare" and interview.status != InterviewStatus.PENDING:
        return write_skipped_run(
            workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "INTERVIEW", interview.id,
            {"interview_id": str(interview.id), "application_id": str(application.id), "phase": phase,
             "status": interview.status},
            _PROMPT_VERSION, "interview not pending",
        )
    skip_reason = guard_limits(workspace_id, config, _AGENT_TYPE)
    if skip_reason:
        return write_skipped_run(
            workspace_id, actor_id, _AGENT_TYPE, HrAgentTriggerType.MANUAL, "INTERVIEW", interview.id,
            {"interview_id": str(interview.id), "phase": phase}, _PROMPT_VERSION, skip_reason,
        )

    expire_pending_proposals_for(workspace_id, "INTERVIEW", str(interview.id))
    run = HrAgentRun.objects.create(
        workspace_id=workspace_id,
        agent_type=_AGENT_TYPE,
        trigger_type=HrAgentTriggerType.MANUAL,
        ref_object_type="INTERVIEW",
        ref_object_id=str(interview.id),
        status=HrAgentRunStatus.RUNNING,
        input_meta={
            "interview_id": str(interview.id),
            "application_id": str(application.id),
            "job_id": str(application.job_id),
            "candidate_id": str(application.candidate_id),
            "phase": phase,
            "round_no": interview.round_no,
            "resume_database_ids": resume_database_ids or [],
        },
        prompt_version=_PROMPT_VERSION,
        user_id=actor_id,
    )
    started = time.monotonic()
    trace = []
    try:
        model, model_name = _load_llm(workspace_id, config)
        if model is None:
            raise RuntimeError("LLM 模型未配置或不可用")

        # 工具 ① get_job
        t0 = time.monotonic()
        job_ctx = context.job_to_llm(application.job)
        trace.append({"tool": "get_job", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})
        # 工具 ② get_candidate_overview
        t0 = time.monotonic()
        candidate_ctx = context.candidate_to_llm(application.candidate)
        trace.append({"tool": "get_candidate_overview", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})

        prompt_kwargs = {
            "job": json.dumps(job_ctx, ensure_ascii=False),
            "candidate": json.dumps(candidate_ctx, ensure_ascii=False),
        }
        allowed_paragraph_ids = None
        if phase == "prepare":
            # 工具 ③ search_resumes（候选人文档集限定，找弱项）
            t0 = time.monotonic()
            document_ids = _candidate_document_ids(workspace_id, application.candidate_id, resume_database_ids)
            weak_spots = _collect_weak_spots(workspace_id, application, document_ids, resume_database_ids)
            # evidence paragraph_id 允许集：来自本次 search_resumes 投影结果（P2-8）
            allowed_paragraph_ids = _allowed_paragraph_ids(weak_spots)
            trace.append({"tool": "search_resumes", "elapsed_ms": int((time.monotonic() - t0) * 1000),
                          "rows": len(weak_spots)})
            # 工具 ④ search_knowledge（企业题库，白名单）
            t0 = time.monotonic()
            question_bank = _collect_question_bank(workspace_id, application.job)
            trace.append({"tool": "search_knowledge", "elapsed_ms": int((time.monotonic() - t0) * 1000),
                          "rows": len(question_bank)})
            # 工具 ⑤ similar_jobs（可选对标）
            t0 = time.monotonic()
            try:
                similar_ctx = context.similar_jobs_to_llm(similar_jobs(workspace_id, str(application.job_id)))
            except AppApiException:
                similar_ctx = []
            trace.append({"tool": "similar_jobs", "elapsed_ms": int((time.monotonic() - t0) * 1000),
                          "rows": len(similar_ctx)})
            prompt = _PREPARE_PROMPT.format(
                **prompt_kwargs,
                weak_spots=json.dumps(weak_spots, ensure_ascii=False),
                question_bank=json.dumps(question_bank, ensure_ascii=False),
                similar_jobs=json.dumps(similar_ctx, ensure_ascii=False),
            )
        else:
            prompt = _FEEDBACK_PROMPT.format(**prompt_kwargs, interview_feedback=json.dumps(feedback, ensure_ascii=False))

        facts = None
        last_error = ""
        for _attempt in range(2):
            try:
                facts = (_validate_prepare_facts if phase == "prepare" else _validate_feedback_facts)(
                    _invoke_llm(model, prompt), allowed_paragraph_ids=allowed_paragraph_ids
                )
                break
            except (ValueError, TypeError, KeyError) as exc:
                last_error = str(exc)
        if facts is None:
            raise RuntimeError(f"LLM output validation failed: {last_error}")

        payload = {"phase": phase, **facts}
        proposal = propose(
            workspace_id, run, str(interview.id), action="DRAFT", payload_json=payload, target_type="INTERVIEW"
        )
        run.output_json = payload
        run.status = HrAgentRunStatus.SUCCEEDED
        run.llm_model = model_name
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(model, "_last_usage", {}) or {}
        run.prompt_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        run.completion_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        run.save(update_fields=["output_json", "status", "llm_model", "tool_trace", "duration_ms", "prompt_tokens", "completion_tokens", "update_time"])
        record_prompt_version(config, _AGENT_TYPE, _PROMPT_VERSION)
        write_audit_log(
            workspace_id, actor_id, "AGENT_RUN", "INTERVIEW", interview.id,
            detail={"agent_type": _AGENT_TYPE, "trigger": "MANUAL", "action": "DRAFT", "phase": phase},
            trace_id=run.id,
        )
        return run_output(run, proposal)
    except Exception as exc:  # noqa: BLE001 - 业务零影响：任何失败仅记录
        run.status = HrAgentRunStatus.FAILED
        run.error = str(exc)[:2000]
        run.tool_trace = trace
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save(update_fields=["status", "error", "tool_trace", "duration_ms", "update_time"])
        write_audit_log(
            workspace_id, actor_id, "AGENT_RUN", "INTERVIEW", interview.id,
            result="FAILED", detail=f"interview copilot failed: {str(exc)[:500]}", trace_id=run.id,
        )
        return run_output(run, None)
