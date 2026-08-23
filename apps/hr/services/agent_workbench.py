# coding=utf-8
"""Agent 工作台查询、详情投影和受控重试服务。"""

from datetime import datetime, time

from django.conf import settings
from django.db.models import Count, F, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

import uuid_utils.compat as uuid

from common.exception.app_exception import AppApiException
from hr.agents.copilot_runner import run_interview_copilot
from hr.agents.draft_runner import run_communication_draft
from hr.agents.jd_runner import run_jd_draft_agent
from hr.agents.runner import run_screening_agent
from hr.agents.sourcing_runner import run_sourcing_agent
from knowledge.models import Paragraph

from hr.models import (
    HrAgentProposal,
    HrAgentProposalStatus,
    HrAgentRun,
    HrAgentRunStatus,
    HrAgentTriggerType,
    ResumeFile,
)

try:
    from hr.agents.copilot_runner_pydantic import run_interview_copilot as run_interview_copilot_pydantic
    from hr.agents.jd_runner_pydantic import run_jd_draft_agent as run_jd_draft_agent_pydantic
    from hr.agents.runner_pydantic import run_screening_agent as run_screening_agent_pydantic
    from hr.agents.sourcing_runner_pydantic import run_sourcing_agent as run_sourcing_agent_pydantic

    _PYDANTIC_AVAILABLE = True
except ImportError:
    _PYDANTIC_AVAILABLE = False


def _use_pydantic():
    return _PYDANTIC_AVAILABLE and getattr(settings, "USE_PYDANTIC_AI", False)


_AGENT_TYPES = {"SCREENING", "JD_DRAFT", "INTERVIEW_COPILOT", "SOURCING", "COMMUNICATION_DRAFT"}
_PAGE_SIZE_MAX = 100


def _iso(value):
    return value.isoformat() if value else None


def _page(params):
    try:
        current_page = max(1, int(params.get("current_page", 1)))
        page_size = min(_PAGE_SIZE_MAX, max(1, int(params.get("page_size", 20))))
    except (TypeError, ValueError) as exc:
        raise AppApiException(400, "current_page and page_size must be integers") from exc
    return current_page, page_size


def _filter_datetime(value, end=False):
    text = str(value)
    parsed_date = parse_date(text)
    if parsed_date is not None:
        parsed = datetime.combine(parsed_date, time.max if end else time.min)
    else:
        parsed = parse_datetime(text)
        if parsed is None:
            raise AppApiException(400, "created_from and created_to must be ISO dates")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _evidence_items(value, path="", output=None):
    output = output if output is not None else []
    if len(output) >= 100:
        return output
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "evidence" and isinstance(child, list):
                for item in child:
                    if not isinstance(item, dict):
                        continue
                    excerpt = str(item.get("excerpt") or "").strip()
                    if not excerpt:
                        continue
                    output.append({
                        "path": child_path,
                        "paragraph_id": item.get("paragraph_id"),
                        "excerpt": excerpt[:1200],
                        "relevance": item.get("relevance"),
                    })
                    if len(output) >= 100:
                        return output
            _evidence_items(child, child_path, output)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _evidence_items(child, f"{path}[{index}]", output)
            if len(output) >= 100:
                break
    return output


def _proposal_projection(proposal, include_payload=True):
    payload = proposal.payload_json if isinstance(proposal.payload_json, dict) else {}
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    evidence = _evidence_items(payload)
    return {
        "id": str(proposal.id),
        "run_id": str(proposal.run_id) if proposal.run_id else None,
        "run_agent_type": proposal.run.agent_type if proposal.run_id and proposal.run else None,
        "target_type": proposal.target_type,
        "target_id": proposal.target_id,
        "action": proposal.action,
        "status": proposal.status,
        "payload": payload if include_payload else None,
        "summary": payload.get("summary") or decision.get("suggested_action", ""),
        "evidence_count": len(evidence),
        "evidence": evidence,
        "decided_by": str(proposal.decided_by) if proposal.decided_by else None,
        "decided_at": _iso(proposal.decided_at),
        "decision_note": proposal.decision_note,
        "create_time": _iso(proposal.create_time),
        "update_time": _iso(proposal.update_time),
    }


def _run_projection(run, include_trace=False, include_output=False):
    projection = {
        "id": str(run.id),
        "workspace_id": run.workspace_id,
        "agent_type": run.agent_type,
        "trigger_type": run.trigger_type,
        "ref_object_type": run.ref_object_type,
        "ref_object_id": run.ref_object_id,
        "status": run.status,
        "input_meta": run.input_meta or {},
        "error": run.error,
        "llm_model": run.llm_model,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "total_tokens": run.prompt_tokens + run.completion_tokens,
        "prompt_version": run.prompt_version,
        "duration_ms": run.duration_ms,
        "proposal_count": getattr(run, "proposal_count", None),
        "create_time": _iso(run.create_time),
        "update_time": _iso(run.update_time),
    }
    if include_trace:
        projection["tool_trace"] = run.tool_trace or []
    if include_output:
        projection["output"] = run.output_json
    return projection


def list_runs(workspace_id, params):
    current_page, page_size = _page(params)
    queryset = HrAgentRun.objects.filter(workspace_id=workspace_id).annotate(
        proposal_count=Count("proposals")
    ).order_by("-create_time")
    agent_type = params.get("agent_type")
    status = params.get("status")
    trigger_type = params.get("trigger_type")
    ref_object_type = params.get("ref_object_type")
    if agent_type:
        if agent_type not in _AGENT_TYPES:
            raise AppApiException(400, "agent_type is invalid")
        queryset = queryset.filter(agent_type=agent_type)
    if status:
        if status not in {choice.value for choice in HrAgentRunStatus}:
            raise AppApiException(400, "status is invalid")
        queryset = queryset.filter(status=status)
    if trigger_type:
        if trigger_type not in {choice.value for choice in HrAgentTriggerType}:
            raise AppApiException(400, "trigger_type is invalid")
        queryset = queryset.filter(trigger_type=trigger_type)
    if ref_object_type:
        queryset = queryset.filter(ref_object_type=ref_object_type)
    ref_object_id = str(params.get("ref_object_id") or "").strip()
    if ref_object_id:
        queryset = queryset.filter(ref_object_id=ref_object_id)
    search = str(params.get("search") or "").strip()
    if search:
        queryset = queryset.filter(
            Q(agent_type__icontains=search)
            | Q(trigger_type__icontains=search)
            | Q(ref_object_type__icontains=search)
            | Q(ref_object_id__icontains=search)
            | Q(input_meta__icontains=search)
        )
    created_from = params.get("created_from")
    if created_from:
        queryset = queryset.filter(create_time__gte=_filter_datetime(created_from))
    created_to = params.get("created_to")
    if created_to:
        queryset = queryset.filter(create_time__lte=_filter_datetime(created_to, end=True))
    total = queryset.count()
    start = (current_page - 1) * page_size
    records = queryset[start:start + page_size]
    summary = queryset.aggregate(
        total_tokens=Sum(F("prompt_tokens") + F("completion_tokens")),
        total_duration_ms=Sum("duration_ms"),
    )
    status_counts = {
        status: count
        for status, count in queryset.values("status").annotate(count=Count("id")).values_list("status", "count")
    }
    return {
        "records": [_run_projection(run) for run in records],
        "total": total,
        "current_page": current_page,
        "page_size": page_size,
        "summary": {
            "total_runs": total,
            "status_counts": status_counts,
            "total_tokens": summary["total_tokens"] or 0,
            "total_duration_ms": summary["total_duration_ms"] or 0,
        },
    }


def get_run(workspace_id, run_id):
    run = HrAgentRun.objects.filter(workspace_id=workspace_id, id=run_id).first()
    if run is None:
        raise AppApiException(404, "Agent run not found")
    proposals = HrAgentProposal.objects.filter(workspace_id=workspace_id, run=run).order_by("-create_time")
    evidence = _evidence_items(run.output_json or {})
    for proposal in proposals:
        _evidence_items(proposal.payload_json or {}, output=evidence)
    return {
        "run": _run_projection(run, include_trace=True, include_output=True),
        "proposals": [_proposal_projection(proposal) for proposal in proposals],
        "evidence": evidence,
    }


def get_evidence_paragraph(workspace_id, paragraph_id):
    try:
        paragraph_uuid = uuid.UUID(str(paragraph_id))
    except (ValueError, TypeError) as exc:
        raise AppApiException(400, "paragraph_id is invalid") from exc
    paragraph = Paragraph.objects.select_related("document").filter(id=paragraph_uuid).first()
    if paragraph is None:
        raise AppApiException(404, "Evidence paragraph not found")
    resume = ResumeFile.objects.filter(
        workspace_id=workspace_id, document_id=paragraph.document_id
    ).first()
    if resume is None:
        raise AppApiException(404, "Evidence paragraph not found")
    return {
        "paragraph_id": str(paragraph.id),
        "document_id": str(paragraph.document_id),
        "resume_id": str(resume.id),
        "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
        "file_name": resume.file_name,
        "title": paragraph.title or "",
        "position": paragraph.position,
        "content": paragraph.content or "",
    }


def list_proposals(workspace_id, params):
    current_page, page_size = _page(params)
    queryset = HrAgentProposal.objects.filter(workspace_id=workspace_id).select_related("run").order_by("-create_time")
    status = params.get("status")
    agent_type = params.get("agent_type")
    action = params.get("action")
    if status:
        if status not in {choice.value for choice in HrAgentProposalStatus}:
            raise AppApiException(400, "proposal status is invalid")
        queryset = queryset.filter(status=status)
    if agent_type:
        if agent_type not in _AGENT_TYPES:
            raise AppApiException(400, "agent_type is invalid")
        queryset = queryset.filter(run__agent_type=agent_type)
    if action:
        queryset = queryset.filter(action=action)
    total = queryset.count()
    start = (current_page - 1) * page_size
    records = queryset[start:start + page_size]
    return {
        "records": [_proposal_projection(proposal) for proposal in records],
        "total": total,
        "current_page": current_page,
        "page_size": page_size,
    }


def retry_run(workspace_id, run_id, user_id, data=None):
    data = data or {}
    run = HrAgentRun.objects.filter(workspace_id=workspace_id, id=run_id).first()
    if run is None:
        raise AppApiException(404, "Agent run not found")
    if run.status not in (HrAgentRunStatus.FAILED, HrAgentRunStatus.SKIPPED):
        raise AppApiException(400, "only FAILED or SKIPPED runs can be retried")
    meta = run.input_meta or {}
    if run.agent_type == "SCREENING":
        _runner = run_screening_agent_pydantic if _use_pydantic() else run_screening_agent
        output = _runner(
            meta.get("application_id") or run.ref_object_id,
            trigger_type=HrAgentTriggerType.MANUAL,
            user_id=user_id,
            workspace_id=workspace_id,
            resume_database_ids=meta.get("resume_database_ids") or [],
        )
    elif run.agent_type == "JD_DRAFT":
        _runner = run_jd_draft_agent_pydantic if _use_pydantic() else run_jd_draft_agent
        output = _runner(
            meta.get("job_id") or run.ref_object_id,
            trigger_type=HrAgentTriggerType.MANUAL,
            user_id=user_id,
            workspace_id=workspace_id,
        )
    elif run.agent_type == "SOURCING":
        _runner = run_sourcing_agent_pydantic if _use_pydantic() else run_sourcing_agent
        output = _runner(
            meta.get("job_id") or run.ref_object_id,
            trigger_type=HrAgentTriggerType.MANUAL,
            user_id=user_id,
            workspace_id=workspace_id,
            data={"resume_database_ids": meta.get("resume_database_ids") or []},
        )
    elif run.agent_type == "INTERVIEW_COPILOT":
        phase = meta.get("phase") or "prepare"
        retry_data = {
            "phase": phase,
            "resume_database_ids": meta.get("resume_database_ids") or [],
        }
        if phase == "feedback":
            feedback = str(data.get("feedback") or "").strip()
            if not feedback:
                raise AppApiException(400, "feedback is required to retry feedback copilot")
            retry_data["feedback"] = feedback
        _runner = run_interview_copilot_pydantic if _use_pydantic() else run_interview_copilot
        output = _runner(
            meta.get("interview_id") or run.ref_object_id,
            data=retry_data,
            user_id=user_id,
            hr_role="OPERATOR",
            workspace_id=workspace_id,
        )
    elif run.agent_type == "COMMUNICATION_DRAFT":
        output = run_communication_draft(
            meta.get("application_id") or run.ref_object_id,
            data={"scenario": meta.get("scenario") or data.get("scenario") or "OTHER"},
            user_id=user_id,
            hr_role="OPERATOR",
            workspace_id=workspace_id,
        )
    else:
        raise AppApiException(400, "agent type cannot be retried")
    return output
