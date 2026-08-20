# coding=utf-8
"""
    @project: MaxKB
    @file： sourcing_runner.py
    @date：2026/8/17
    @desc: Sourcing 人才库激活 Agent（PRD-AGENT-RAG §5 Agent 清单，D3）：
           OPEN 职位人工触发；固定顺序工具编排（get_job → search_resumes 全库 → structured_filter）
           + 单次 LLM 梳理优先级清单 + propose(action=DRAFT, target=JOB)。
           只出内部清单、不外发；已在该职位有申请（含历史）的候选人由服务端剔除（沉睡候选人才池）。
"""
import json
import time
import uuid

from common.exception.app_exception import AppApiException
from hr.agents import context
from hr.agents.base import guard_limits, record_prompt_version, run_output, write_skipped_run
from hr.agents.proposals import expire_pending_proposals_for, propose
from hr.agents.runner import _config, _invoke_llm, _load_llm, structured_filter
from hr.agents.scope import validate_resume_database_ids
from hr.models import (
    Application,
    Candidate,
    HrAgentRun,
    HrAgentRunStatus,
    HrAgentTriggerType,
    HrAgentType,
    Job,
    JobStatus,
)
from hr.services.audit import write_audit_log
from hr.services.resume_search import search_resumes

_SYSTEM_USER_ID = uuid.UUID(int=0)
_AGENT_TYPE = HrAgentType.SOURCING
_PROMPT_VERSION = "sourcing-v1"
_MAX_SEARCHES = 3
_MAX_CANDIDATES = 10


def _sleeping_pool(workspace_id, job, search_items):
    """服务端剔除：该职位已有申请（含历史）的候选人不出现在清单（沉睡候选人定义）。"""
    applied = set(
        Application.objects.filter(workspace_id=workspace_id, job=job).values_list("candidate_id", flat=True)
    )
    pool = []
    for item in (search_items or []):
        candidate = (item.get("candidate") or {})
        candidate_id = str(candidate.get("id") or "")
        if not candidate_id or candidate_id in applied:
            continue
        pool.append(item)
    return pool


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


def _facts_from_llm(model, prompt, allowed_ids):
    data = _invoke_llm(model, prompt)
    if not isinstance(data, dict):
        raise ValueError("sourcing result must be an object")
    candidates = []
    for item in (data.get("candidates") or []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        if not candidate_id or candidate_id not in allowed_ids:
            continue
        evidence = []
        for entry in (item.get("evidence") or []):
            if isinstance(entry, dict):
                evidence.append({
                    "paragraph_id": entry.get("paragraph_id"),
                    "excerpt": str(entry.get("excerpt") or "")[:500],
                    "relevance": float(entry.get("relevance", 0) or 0),
                })
        candidates.append({
            "candidate_id": candidate_id,
            "match_reason": str(item.get("match_reason") or "")[:1000],
            "risk": str(item.get("risk") or "")[:500],
            "evidence": evidence,
        })
    if not candidates:
        raise ValueError("candidates must be a non-empty list with ids from the pool")
    return {
        "candidates": candidates[:_MAX_CANDIDATES],
        "summary": str(data.get("summary") or "").strip()[:1000],
    }


def run_sourcing_agent(job_id, trigger_type=HrAgentTriggerType.MANUAL, user_id=None, workspace_id=None, data=None):
    """执行一次 Sourcing 运行；任何失败 run=FAILED，职位与人才库不受影响。
    workspace_id 由 API 传入时强制校验归属。"""
    job = Job.objects.filter(id=job_id).first()
    if job is None:
        return None
    if workspace_id is not None and str(job.workspace_id) != str(workspace_id):
        return None
    workspace_id = job.workspace_id
    data = data or {}
    resume_database_ids = validate_resume_database_ids(
        workspace_id, data.get("resume_database_ids") or data.get("resume_database_id")
    )
    actor_id = user_id or job.user_id or _SYSTEM_USER_ID
    config = _config(workspace_id)
    if job.status != JobStatus.OPEN:
        return write_skipped_run(
            workspace_id, actor_id, _AGENT_TYPE, trigger_type, "JOB", job.id,
            {"job_id": str(job.id), "job_name": job.name, "status": job.status},
            _PROMPT_VERSION, "sourcing requires an OPEN job",
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
        input_meta={
            "job_id": str(job.id),
            "job_name": job.name,
            "department": job.department,
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
        job_ctx = context.job_to_llm(job)
        trace.append({"tool": "get_job", "elapsed_ms": int((time.monotonic() - t0) * 1000), "rows": 1})

        # 工具 ② search_resumes（全库召回，召回结果仅用于沉睡池构建）
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
                raw = search_resumes(
                    workspace_id, query, top_k=8, mode="phrase", hr_role="VIEWER", user_id=None,
                    llm_model=None, rerank_model=None,
                    resume_database_ids=resume_database_ids,
                )
            except AppApiException:
                continue
            recalled.extend(raw.get("items") or [])
        t0 = time.monotonic()
        trace.append({"tool": "search_resumes", "elapsed_ms": int((time.monotonic() - t0) * 1000),
                      "rows": len(recalled)})

        # 工具 ③ structured_filter（硬条件核对，仅保留 hard_met）— 批量查询消除 N+1
        t0 = time.monotonic()
        pool_items = []
        seen = set()
        candidate_ids = []
        for item in recalled:
            candidate_id = str((item.get("candidate") or {}).get("id") or "")
            if not candidate_id or candidate_id in seen:
                continue
            seen.add(candidate_id)
            candidate_ids.append(candidate_id)
        # 批量拉取候选人，避免逐条查询的 N+1
        candidate_map = {
            str(candidate.id): candidate
            for candidate in Candidate.objects.filter(id__in=candidate_ids, workspace_id=workspace_id)
        }
        seen.clear()
        for item in recalled:
            candidate_id = str((item.get("candidate") or {}).get("id") or "")
            if not candidate_id or candidate_id in seen:
                continue
            seen.add(candidate_id)
            candidate = candidate_map.get(candidate_id)
            if candidate is None:
                continue
            check = structured_filter(job, candidate)
            if not check["hard_met"]:
                continue
            pool_items.append(item)
        trace.append({"tool": "structured_filter", "elapsed_ms": int((time.monotonic() - t0) * 1000),
                      "rows": len(pool_items)})

        sleeping = _sleeping_pool(workspace_id, job, pool_items)
        if not sleeping:
            raise RuntimeError("no sleeping candidates after structured filter")

        allowed_ids = {str((item.get("candidate") or {}).get("id")) for item in sleeping}
        projected = context.search_to_llm({"items": sleeping, "meta": {}})
        prompt = _SOURCING_PROMPT.format(
            job=json.dumps(job_ctx, ensure_ascii=False),
            candidate_pool=json.dumps(projected, ensure_ascii=False),
            max_candidates=_MAX_CANDIDATES,
        )
        facts = None
        last_error = ""
        for _attempt in range(2):
            try:
                facts = _facts_from_llm(model, prompt, allowed_ids)
                break
            except (ValueError, TypeError, KeyError) as exc:
                last_error = str(exc)
        if facts is None:
            raise RuntimeError(f"LLM output validation failed: {last_error}")

        # 组装最终清单：以 LLM 顺序为准，回填结构化字段
        by_id = {str((item.get("candidate") or {}).get("id")): item for item in sleeping}
        candidates = []
        for row in facts["candidates"]:
            item = by_id[row["candidate_id"]]
            candidate = item.get("candidate") or {}
            candidates.append({
                **row,
                "name": candidate.get("name"),
                "current_city": candidate.get("current_city"),
                "highest_degree": candidate.get("highest_degree"),
                "years_experience": candidate.get("years_experience"),
                "skills": candidate.get("skills"),
                "document_id": item.get("document_id"),
            })
        payload = {
            "scope": {"job_id": str(job.id), "job_name": job.name},
            "candidates": candidates,
            "summary": facts["summary"],
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
                    "candidates": len(candidates), "summary": facts["summary"][:200]},
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
            result="FAILED", detail=f"sourcing agent failed: {str(exc)[:500]}", trace_id=run.id,
        )
        return run_output(run, None)
