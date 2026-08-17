# coding=utf-8
"""
    @project: MaxKB
    @file： agent_stats.py
    @date：2026/8/17
    @desc: Agent 反馈闭环统计（PRD-AGENT-RAG §8 反馈闭环 / D3）：
           按 agent_type 聚合运行账本与提案决策（采纳/忽略/过期/待决），
           并按分数带统计采纳率——供 dashboard 与阈值标定使用。
"""
from django.db.models import Count, Q

from hr.models import HrAgentProposal, HrAgentProposalStatus, HrAgentRun, HrAgentRunStatus


def _band(score):
    """分数带：None / 0-59 / 60-79 / 80-100。"""
    if score is None:
        return "no-score"
    if score < 60:
        return "0-59"
    if score < 80:
        return "60-79"
    return "80-100"


def _proposal_decision_rows(workspace_id, agent_type=None):
    proposals = HrAgentProposal.objects.filter(workspace_id=workspace_id).select_related("run")
    if agent_type:
        proposals = proposals.filter(run__agent_type=agent_type)
    rows = []
    for proposal in proposals.iterator():
        run = proposal.run
        payload = proposal.payload_json or {}
        decision = payload.get("decision") or {}
        rows.append({
            "agent_type": run.agent_type if run else "UNKNOWN",
            "action": proposal.action,
            "status": proposal.status,
            "score": decision.get("score"),
            "suggested_action": decision.get("suggested_action"),
        })
    return rows


def agent_feedback_stats(workspace_id):
    """按 agent_type 汇总运行数与提案决策采纳率（含分数带明细）。"""
    run_rows = (
        HrAgentRun.objects.filter(workspace_id=workspace_id)
        .values("agent_type")
        .annotate(
            total=Count("id"),
            succeeded=Count("id", filter=Q(status=HrAgentRunStatus.SUCCEEDED)),
            failed=Count("id", filter=Q(status=HrAgentRunStatus.FAILED)),
            skipped=Count("id", filter=Q(status=HrAgentRunStatus.SKIPPED)),
        )
        .order_by("agent_type")
    )
    run_map = {row["agent_type"]: row for row in run_rows}

    proposal_rows = _proposal_decision_rows(workspace_id)
    agents = sorted({row["agent_type"] for row in proposal_rows} | set(run_map.keys()))
    by_agent = []
    for agent_type in agents:
        rows = [row for row in proposal_rows if row["agent_type"] == agent_type]
        action_stats = {}
        for row in rows:
            action = row["action"]
            bucket = action_stats.setdefault(action, {"PENDING": 0, "ACCEPTED": 0, "DISMISSED": 0, "EXPIRED": 0})
            bucket[row["status"]] = bucket.get(row["status"], 0) + 1
        decided = sum(
            bucket["ACCEPTED"] + bucket["DISMISSED"] + bucket["EXPIRED"]
            for bucket in action_stats.values()
        )
        accepted = sum(bucket["ACCEPTED"] for bucket in action_stats.values())
        band_rows = {}
        for row in rows:
            if row["action"] not in ("ADVANCE", "DECLINE", "HOLD"):
                continue
            key = _band(row["score"])
            bucket = band_rows.setdefault(key, {"count": 0, "accepted": 0, "decided": 0})
            bucket["count"] += 1
            if row["status"] != HrAgentProposalStatus.PENDING:
                bucket["decided"] += 1
                if row["status"] == HrAgentProposalStatus.ACCEPTED:
                    bucket["accepted"] += 1
        band_output = {}
        for key, bucket in sorted(band_rows.items()):
            band_output[key] = {
                "count": bucket["count"],
                "decided": bucket["decided"],
                "accept_rate": round(bucket["accepted"] / bucket["decided"], 3) if bucket["decided"] else None,
            }
        run = run_map.get(agent_type)
        by_agent.append({
            "agent_type": agent_type,
            "runs": run["total"] if run else 0,
            "succeeded": run["succeeded"] if run else 0,
            "failed": run["failed"] if run else 0,
            "skipped": run["skipped"] if run else 0,
            "proposals": action_stats,
            "proposal_total": len(rows),
            "decided": decided,
            "accepted": accepted,
            "accept_rate": round(accepted / decided, 3) if decided else None,
            "score_bands": band_output,
        })
    return {"by_agent": by_agent}
