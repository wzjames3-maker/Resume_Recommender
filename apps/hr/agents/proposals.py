# coding=utf-8
"""
    @project: MaxKB
    @file： proposals.py
    @date：2026/8/17
    @desc: HrAgentProposal 审批命令（Propose → Confirm → Execute）：
           accept 按 action 调用 ATS v2 命令层（ADVANCE→move_stage(next) / DECLINE→reject(NOT_FIT) / HOLD→不改状态），
           幂等键 proposal:{proposal_id}；dismiss/expire 更新提案状态；决策权限 OPERATOR+ 且 owner 或 ADMIN。
"""
from django.db import transaction
from django.utils import timezone

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    Application,
    ApplicationStatus,
    HrAgentProposal,
    HrAgentProposalAction,
    HrAgentProposalStatus,
    JobStage,
)
from hr.services.application_service import ApplicationService
from hr.services.audit import write_audit_log


def propose(workspace_id, run, target_id, action, payload_json):
    """Runner 的唯一写出口：同目标旧的 PENDING Proposal 自动 EXPIRED（§4.4）。"""
    HrAgentProposal.objects.filter(
        workspace_id=workspace_id,
        target_type="APPLICATION",
        target_id=str(target_id),
        status=HrAgentProposalStatus.PENDING,
    ).update(status=HrAgentProposalStatus.EXPIRED, update_time=timezone.now())
    return HrAgentProposal.objects.create(
        workspace_id=workspace_id,
        run=run,
        target_type="APPLICATION",
        target_id=str(target_id),
        action=action,
        payload_json=payload_json,
        user_id=run.user_id,
    )


def expire_pending_proposals(workspace_id, target_id):
    """目标状态/阶段已变迁的 PENDING 提案自动 EXPIRED（惰性失效）。"""
    proposals = HrAgentProposal.objects.filter(
        workspace_id=workspace_id,
        target_type="APPLICATION",
        target_id=str(target_id),
        status=HrAgentProposalStatus.PENDING,
    )
    for proposal in proposals:
        application = Application.objects.filter(id=target_id, workspace_id=workspace_id).first()
        stage_key = (proposal.payload_json or {}).get("stage_key")
        stale = (
            application is None
            or application.status != ApplicationStatus.ACTIVE
            or (stage_key and (application.current_stage is None or application.current_stage.key != stage_key))
        )
        if stale:
            proposal.status = HrAgentProposalStatus.EXPIRED
            proposal.save(update_fields=["status", "update_time"])


def _is_stale(application, proposal):
    stage_key = (proposal.payload_json or {}).get("stage_key")
    return (
        application is None
        or application.status != ApplicationStatus.ACTIVE
        or (stage_key and (application.current_stage is None or application.current_stage.key != stage_key))
    )


class ProposalService:
    def __init__(self, workspace_id, user_id, hr_role):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.hr_role = hr_role

    def _require_operator(self):
        if self.hr_role not in ("OPERATOR", "ADMIN"):
            write_audit_log(
                self.workspace_id, self.user_id, "ACCESS_DENIED", "OTHER",
                result="DENIED", detail="Operator permission is required",
            )
            raise AppUnauthorizedFailed(403, "Operator permission is required")

    def _proposal(self, proposal_id, for_update=False):
        queryset = HrAgentProposal.objects.filter(id=proposal_id, workspace_id=self.workspace_id)
        if for_update:
            # run 外键可空：只锁提案表自身，避免 FOR UPDATE 与 nullable 外连接冲突
            queryset = queryset.select_for_update(of=("self",))
        proposal = queryset.select_related("run").first()
        if proposal is None:
            raise NotFound404(404, "Resource not found")
        return proposal

    def _target_application(self, proposal):
        application = Application.objects.filter(
            id=proposal.target_id, workspace_id=self.workspace_id
        ).select_related("current_stage").first()
        return application

    def _require_decision_permission(self, application):
        """决策要求 OPERATOR+，且操作者为关联 owner_id 或 ADMIN（PRD-AGENT-RAG §9）。"""
        self._require_operator()
        if self.hr_role == "ADMIN":
            return
        if self.user_id and application is not None and self.user_id == application.owner_id:
            return
        raise AppUnauthorizedFailed(403, "Only the application owner or admin can decide")

    # ---------- 查询 ----------
    def list_for_application(self, application_id):
        application = Application.objects.filter(id=application_id, workspace_id=self.workspace_id).first()
        if application is None:
            raise NotFound404(404, "Resource not found")
        expire_pending_proposals(self.workspace_id, application_id)
        proposals = HrAgentProposal.objects.filter(
            workspace_id=self.workspace_id,
            target_type="APPLICATION",
            target_id=str(application_id),
        ).select_related("run").order_by("-create_time")
        return [self._output(proposal) for proposal in proposals]

    # ---------- 命令 ----------
    def accept(self, proposal_id, data):
        self._require_operator()
        decision_note = str(data.get("decision_note") or "").strip()[:2000]
        # 过期检测与落库在事务外执行（避免异常回滚丢失 EXPIRED 状态）
        proposal = self._proposal(proposal_id)
        application = self._target_application(proposal)
        if _is_stale(application, proposal):
            proposal.status = HrAgentProposalStatus.EXPIRED
            proposal.save(update_fields=["status", "update_time"])
            raise AppApiException(409, "Proposal expired: target application state changed")
        with transaction.atomic():
            proposal = self._proposal(proposal_id, for_update=True)
            application = self._target_application(proposal)
            self._require_decision_permission(application)
            if proposal.status != HrAgentProposalStatus.PENDING:
                raise AppApiException(400, "Proposal is not pending")
            if _is_stale(application, proposal):
                # 事务内重校验：预检通过后目标可能已被并发变更
                raise AppApiException(409, "Proposal expired: target application state changed")
            if application is None or application.status != ApplicationStatus.ACTIVE:
                raise AppApiException(409, "Proposal expired: target application state changed")

            service = ApplicationService(self.workspace_id, self.user_id, self.hr_role)
            idempotency_key = f"proposal:{proposal.id}"
            if proposal.action == HrAgentProposalAction.ADVANCE:
                current = application.current_stage
                if current is None:
                    raise AppApiException(400, "Application has no current stage")
                next_stage = JobStage.objects.filter(
                    workspace_id=self.workspace_id, job=application.job, order__gt=current.order
                ).order_by("order").first()
                if next_stage is None:
                    raise AppApiException(400, "No next stage to advance to")
                service.move_stage(
                    proposal.target_id,
                    next_stage.id,
                    {"reason_text": decision_note or "agent ADVANCE accepted", "idempotency_key": idempotency_key},
                )
            elif proposal.action == HrAgentProposalAction.DECLINE:
                service.reject_application(
                    proposal.target_id,
                    {
                        "termination_reason": "NOT_FIT",
                        "reason_text": decision_note or "agent DECLINE accepted",
                        "idempotency_key": idempotency_key,
                    },
                )
            # HOLD：不改状态
            proposal.status = HrAgentProposalStatus.ACCEPTED
            proposal.decided_by = self.user_id
            proposal.decided_at = timezone.now()
            proposal.decision_note = decision_note
            proposal.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "update_time"])
        write_audit_log(
            self.workspace_id, self.user_id, "AGENT_DECIDE", "APPLICATION", proposal.target_id,
            detail=f"accept {proposal.action} note={decision_note[:200]}",
            trace_id=proposal.run_id if proposal.run_id else "",
        )
        return self._output(proposal)

    def dismiss(self, proposal_id, data):
        self._require_operator()
        decision_note = str(data.get("decision_note") or "").strip()[:2000]
        with transaction.atomic():
            proposal = self._proposal(proposal_id, for_update=True)
            application = self._target_application(proposal)
            self._require_decision_permission(application)
            if proposal.status != HrAgentProposalStatus.PENDING:
                raise AppApiException(400, "Proposal is not pending")
            proposal.status = HrAgentProposalStatus.DISMISSED
            proposal.decided_by = self.user_id
            proposal.decided_at = timezone.now()
            proposal.decision_note = decision_note
            proposal.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "update_time"])
        write_audit_log(
            self.workspace_id, self.user_id, "AGENT_DECIDE", "APPLICATION", proposal.target_id,
            detail=f"dismiss {proposal.action} note={decision_note[:200]}",
            trace_id=proposal.run_id if proposal.run_id else "",
        )
        return self._output(proposal)

    # ---------- 输出 ----------
    @staticmethod
    def _output(proposal):
        return {
            "id": str(proposal.id),
            "run_id": str(proposal.run_id) if proposal.run_id else None,
            "target_type": proposal.target_type,
            "target_id": proposal.target_id,
            "action": proposal.action,
            "status": proposal.status,
            "payload": proposal.payload_json,
            "decided_by": str(proposal.decided_by) if proposal.decided_by else None,
            "decided_at": proposal.decided_at,
            "decision_note": proposal.decision_note,
            "create_time": proposal.create_time,
            "update_time": proposal.update_time,
        }
