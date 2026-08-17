# coding=utf-8
"""
    @project: MaxKB
    @file： base.py
    @date：2026/8/17
    @desc: D2 Agent Runner 共享辅助（JD 起草 / Interview Copilot）：
           复用 Screener 的模型加载/JSON 调用惯例（hr.agents.runner），
           提供按 agent_type 通用的并发/速率护栏、跳过运行落库与运行输出。
"""
import uuid

from django.utils import timezone

from hr.models import HrAgentRun, HrAgentRunStatus
from hr.services.audit import write_audit_log

_SYSTEM_USER_ID = uuid.UUID(int=0)


def guard_limits(workspace_id, config, agent_type):
    """并发与速率护栏（按 agent_type 独立统计）：超限返回跳过原因，否则 None。"""
    concurrent = HrAgentRun.objects.filter(
        workspace_id=workspace_id,
        agent_type=agent_type,
        status__in=[HrAgentRunStatus.PENDING, HrAgentRunStatus.RUNNING],
    ).count()
    if concurrent >= config.agent_max_concurrent_runs:
        return f"concurrent run limit reached ({config.agent_max_concurrent_runs})"
    since = timezone.now() - timezone.timedelta(hours=1)
    recent = HrAgentRun.objects.filter(
        workspace_id=workspace_id, agent_type=agent_type, create_time__gte=since
    ).count()
    if recent >= config.agent_run_rate_limit:
        return f"rate limit reached ({config.agent_run_rate_limit}/hour)"
    return None


def record_prompt_version(config, agent_type, version):
    """只读记录各 Agent 生效提示词版本（HrConfig.agent_prompt_versions，§8）。"""
    versions = dict(config.agent_prompt_versions or {})
    if versions.get(agent_type) != version:
        versions[agent_type] = version
        config.agent_prompt_versions = versions
        config.save(update_fields=["agent_prompt_versions", "update_time"])


def write_skipped_run(workspace_id, actor_id, agent_type, trigger_type, ref_object_type, ref_object_id,
                      input_meta, prompt_version, reason):
    run = HrAgentRun.objects.create(
        workspace_id=workspace_id,
        agent_type=agent_type,
        trigger_type=trigger_type,
        ref_object_type=ref_object_type,
        ref_object_id=str(ref_object_id),
        status=HrAgentRunStatus.SKIPPED,
        input_meta=input_meta,
        error=reason,
        prompt_version=prompt_version,
        user_id=actor_id,
    )
    write_audit_log(
        workspace_id, actor_id, "AGENT_RUN", ref_object_type, ref_object_id,
        result="SKIPPED", detail=reason, trace_id=run.id,
    )
    return run_output(run, None)


def run_output(run, proposal):
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
