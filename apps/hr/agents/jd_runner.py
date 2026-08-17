# coding=utf-8
"""
    @project: MaxKB
    @file： jd_runner.py
    @date：2026/8/17
    @desc: JD 起草 Agent（PRD-AGENT-RAG §5 Agent 清单，D2）：
           人工触发；固定顺序工具编排（get_job → search_knowledge(JD 模板) → similar_jobs 对标）
           + 单次 LLM 生成 JD 草稿 + propose(action=DRAFT, target=JOB)。
           草稿免审；采纳（写入字段）由 HR 在 Proposal 审批时确认，不改变职位状态。
"""
import json
import time
import uuid

from common.exception.app_exception import AppApiException
from hr.agents import context
from hr.agents.base import guard_limits, record_prompt_version, run_output, write_skipped_run
from hr.agents.proposals import expire_pending_proposals_for, propose
from hr.agents.runner import _config, _invoke_llm, _load_llm
from hr.models import HrAgentRun, HrAgentRunStatus, HrAgentTriggerType, HrAgentType, Job, JobStatus
from hr.services.audit import write_audit_log
from hr.services.knowledge_search import search_knowledge
from hr.services.similar_jobs import similar_jobs

_SYSTEM_USER_ID = uuid.UUID(int=0)
_AGENT_TYPE = HrAgentType.JD_DRAFT
_PROMPT_VERSION = "jd-draft-v1"
_MAX_KNOWLEDGE_QUERIES = 3

_JD_DRAFT_PROMPT = """你是招聘 JD 起草助手，为职位 Y 起草招聘启事。
输入：
<job>{job}</job>
<knowledge_templates>{knowledge_templates}</knowledge_templates>
<similar_jobs>{similar_jobs}</similar_jobs>

要求：
1. 以 <job> 的既有信息为前提；<knowledge_templates> 提供企业 JD 模板/职级标准参考，
   <similar_jobs> 提供历史相似职位及其录用画像对标。
2. 输出一份完整、可用、符合企业风格的职位描述草稿（description，Markdown，含岗位职责/任职要求/加分项）。
3. 只输出一个 JSON 对象（不要输出任何其他内容），结构如下：
{{
  "name": "建议职位名称（无需调整则原样填回当前名称）",
  "description": "完整 JD 草稿",
  "skill_requirements": ["技能要求列表"],
  "summary": "一句话说明草稿依据（对标了哪些模板/相似职位）",
  "sources": [{{"kind": "knowledge|similar_job", "ref": "来源标识（知识库/文档名或职位名）", "note": "借鉴点"}}]
}}
4. 借鉴模板要点而非整段复制；录用画像只作对标参考，不得编造职位要求之外的硬条件。
5. 禁止歧视性表述（性别/年龄/婚育/民族/院校出身）；禁止编造不存在的福利与要求。
"""


def _facts_from_llm(model, prompt):
    data = _invoke_llm(model, prompt)
    if not isinstance(data, dict):
        raise ValueError("jd draft must be an object")
    description = str(data.get("description") or "").strip()
    if not description:
        raise ValueError("description is required")
    name = str(data.get("name") or "").strip()
    skills = [str(skill).strip() for skill in (data.get("skill_requirements") or []) if str(skill).strip()]
    sources = []
    for source in (data.get("sources") or []):
        if isinstance(source, dict):
            sources.append({
                "kind": str(source.get("kind") or "")[:20],
                "ref": str(source.get("ref") or "")[:200],
                "note": str(source.get("note") or "")[:500],
            })
    return {
        "name": name,
        "description": description[:8000],
        "skill_requirements": skills[:20],
        "summary": str(data.get("summary") or "").strip()[:1000],
        "sources": sources[:10],
    }


def _collect_templates(workspace_id, job):
    """企业知识库检索（白名单）：对职位名/技能/部门分别检索 JD 模板。"""
    queries = []
    if job.name:
        queries.append(job.name)
    if job.skill_requirements:
        queries.append(" ".join(job.skill_requirements))
    if job.department:
        queries.append(f"{job.department} 岗位 职责 要求")
    hits = []
    for query in queries[:_MAX_KNOWLEDGE_QUERIES]:
        try:
            raw = search_knowledge(workspace_id, query, top_k=5)
        except AppApiException:
            continue
        projected = context.knowledge_to_llm(raw)
        if projected["items"]:
            hits.append({"query": query[:100], **projected})
    return hits


def run_jd_draft_agent(job_id, trigger_type=HrAgentTriggerType.MANUAL, user_id=None, workspace_id=None):
    """执行一次 JD 起草运行；任何失败 run=FAILED，职位编辑不受影响。
    workspace_id 由 API 传入时强制校验归属。"""
    job = Job.objects.filter(id=job_id).first()
    if job is None:
        return None
    if workspace_id is not None and str(job.workspace_id) != str(workspace_id):
        return None
    workspace_id = job.workspace_id
    actor_id = user_id or job.user_id or _SYSTEM_USER_ID
    config = _config(workspace_id)
    if job.status == JobStatus.CLOSED:
        return write_skipped_run(
            workspace_id, actor_id, _AGENT_TYPE, trigger_type, "JOB", job.id,
            {"job_id": str(job.id), "job_name": job.name}, _PROMPT_VERSION, "job closed",
        )
    skip_reason = guard_limits(workspace_id, config, _AGENT_TYPE)
    if skip_reason:
        return write_skipped_run(
            workspace_id, actor_id, _AGENT_TYPE, trigger_type, "JOB", job.id,
            {"job_id": str(job.id), "job_name": job.name}, _PROMPT_VERSION, skip_reason,
        )

    expire_pending_proposals_for(workspace_id, "JOB", str(job.id))
    run = HrAgentRun.objects.create(
        workspace_id=workspace_id,
        agent_type=_AGENT_TYPE,
        trigger_type=trigger_type,
        ref_object_type="JOB",
        ref_object_id=str(job.id),
        status=HrAgentRunStatus.RUNNING,
        input_meta={"job_id": str(job.id), "job_name": job.name, "department": job.department},
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
        job_ctx = context.job_to_llm(job)
        trace.append({"tool": "get_job", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})
        # 工具 ② search_knowledge（JD 模板，白名单内企业知识库）
        t0 = time.monotonic()
        template_hits = _collect_templates(workspace_id, job)
        trace.append({"tool": "search_knowledge", "elapsed_ms": int((time.monotonic() - t0) * 1000),
                      "rows": len(template_hits)})
        # 工具 ③ similar_jobs（SQL 相似 + HIRED 画像）
        t0 = time.monotonic()
        try:
            similar_ctx = context.similar_jobs_to_llm(similar_jobs(workspace_id, str(job.id)))
        except AppApiException:
            similar_ctx = []
        trace.append({"tool": "similar_jobs", "elapsed_ms": int((time.monotonic() - t0) * 1000),
                      "rows": len(similar_ctx)})

        prompt = _JD_DRAFT_PROMPT.format(
            job=json.dumps(job_ctx, ensure_ascii=False),
            knowledge_templates=json.dumps(template_hits, ensure_ascii=False),
            similar_jobs=json.dumps(similar_ctx, ensure_ascii=False),
        )
        facts = None
        last_error = ""
        for _attempt in range(2):
            try:
                facts = _facts_from_llm(model, prompt)
                break
            except (ValueError, TypeError, KeyError) as exc:
                last_error = str(exc)
        if facts is None:
            raise RuntimeError(f"LLM output validation failed: {last_error}")

        payload = {
            "draft_target": "JOB",
            "fields": {
                "name": facts["name"] or job.name,
                "description": facts["description"],
                "skill_requirements": facts["skill_requirements"] or (job.skill_requirements or []),
            },
            "summary": facts["summary"],
            "sources": facts["sources"],
        }
        proposal = propose(
            workspace_id, run, str(job.id), action="DRAFT", payload_json=payload, target_type="JOB"
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
            workspace_id, actor_id, "AGENT_RUN", "JOB", job.id,
            detail={"agent_type": _AGENT_TYPE, "trigger": trigger_type, "action": "DRAFT",
                    "summary": facts["summary"][:200]},
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
            workspace_id, actor_id, "AGENT_RUN", "JOB", job.id,
            result="FAILED", detail=f"jd draft agent failed: {str(exc)[:500]}", trace_id=run.id,
        )
        return run_output(run, None)
