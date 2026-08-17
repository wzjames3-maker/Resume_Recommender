# coding=utf-8
"""
    @project: MaxKB
    @file： proposals.py
    @date：2026/8/17
    @desc: HrAgentProposal 审批命令（Propose → Confirm → Execute）：
           accept 按 target_type × action 执行：
             APPLICATION × ADVANCE → move_stage(next)；× DECLINE → reject(NOT_FIT)；× HOLD → 不改状态；
             JOB × DRAFT → 采纳草稿文本写入 Job 字段（不改状态，ADMIN）；
             INTERVIEW × DRAFT → 仅确认草稿（面试反馈永远人工提交）。
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
    Interview,
    InterviewStatus,
    Job,
    JobStatus,
    JobStage,
)
from hr.services.application_service import ApplicationService
from hr.services.audit import write_audit_log


def propose(workspace_id, run, target_id, action, payload_json, target_type="APPLICATION"):
    """Runner 的唯一写出口：同目标（target_type+target_id）旧的 PENDING Proposal 自动 EXPIRED（§4.4）。"""
    HrAgentProposal.objects.filter(
        workspace_id=workspace_id,
        target_type=target_type,
        target_id=str(target_id),
        status=HrAgentProposalStatus.PENDING,
    ).update(status=HrAgentProposalStatus.EXPIRED, update_time=timezone.now())
    return HrAgentProposal.objects.create(
        workspace_id=workspace_id,
        run=run,
        target_type=target_type,
        target_id=str(target_id),
        action=action,
        payload_json=payload_json,
        user_id=run.user_id,
    )


def _application_stale(application, proposal):
    stage_key = (proposal.payload_json or {}).get("stage_key")
    return (
        application is None
        or application.status != ApplicationStatus.ACTIVE
        or (stage_key and (application.current_stage is None or application.current_stage.key != stage_key))
    )


def _job_stale(job):
    return job is None or job.status == JobStatus.CLOSED


def _interview_stale(interview, payload=None):
    """prepare 提案：反馈已提交/取消即失效；feedback 提案：仅取消失效（评估草稿仍可采纳）。"""
    if interview is None:
        return True
    phase = (payload or {}).get("phase")
    if phase == "feedback":
        return interview.status == InterviewStatus.CANCELLED
    return interview.status != InterviewStatus.PENDING


def _target_stale(workspace_id, proposal):
    """按 target_type 惰性失效检测：目标不存在或状态已变迁 → stale。"""
    if proposal.target_type == "JOB":
        job = Job.objects.filter(id=proposal.target_id, workspace_id=workspace_id).first()
        return _job_stale(job)
    if proposal.target_type == "INTERVIEW":
        interview = Interview.objects.filter(id=proposal.target_id, workspace_id=workspace_id).first()
        return _interview_stale(interview, proposal.payload_json)
    application = Application.objects.filter(id=proposal.target_id, workspace_id=workspace_id).first()
    return _application_stale(application, proposal)


def expire_pending_proposals(workspace_id, target_id):
    """APPLICATION 目标 PENDING 提案惰性失效（沿用旧签名，Screening 链路）。"""
    proposals = HrAgentProposal.objects.filter(
        workspace_id=workspace_id,
        target_type="APPLICATION",
        target_id=str(target_id),
        status=HrAgentProposalStatus.PENDING,
    )
    for proposal in proposals:
        application = Application.objects.filter(id=target_id, workspace_id=workspace_id).first()
        if _application_stale(application, proposal):
            proposal.status = HrAgentProposalStatus.EXPIRED
            proposal.save(update_fields=["status", "update_time"])


def expire_pending_proposals_for(workspace_id, target_type, target_id):
    """任意目标类型 PENDING 提案惰性失效（D2：JOB / INTERVIEW）。"""
    proposals = HrAgentProposal.objects.filter(
        workspace_id=workspace_id,
        target_type=target_type,
        target_id=str(target_id),
        status=HrAgentProposalStatus.PENDING,
    )
    for proposal in proposals:
        if _target_stale(workspace_id, proposal):
            proposal.status = HrAgentProposalStatus.EXPIRED
            proposal.save(update_fields=["status", "update_time"])


def _is_stale(application, proposal):
    return _application_stale(application, proposal)


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

    def _require_decision_permission(self, application, proposal=None):
        """决策要求 OPERATOR+，且操作者为关联 owner_id 或 ADMIN（PRD-AGENT-RAG §9）。
        JOB 目标草稿写入沿职位编辑权限（ADMIN）；INTERVIEW 目标确认要求 OPERATOR+。"""
        self._require_operator()
        if self.hr_role == "ADMIN":
            return
        if proposal is not None and proposal.target_type == "JOB":
            raise AppUnauthorizedFailed(403, "Only workspace ADMIN can apply a JD draft")
        if proposal is not None and proposal.target_type == "INTERVIEW":
            return
        if self.user_id and application is not None and self.user_id == application.owner_id:
            return
        raise AppUnauthorizedFailed(403, "Only the application owner or admin can decide")

    # ---------- 查询 ----------
    def _list(self, target_type, target_id):
        expire_pending_proposals_for(self.workspace_id, target_type, target_id)
        proposals = HrAgentProposal.objects.filter(
            workspace_id=self.workspace_id,
            target_type=target_type,
            target_id=str(target_id),
        ).select_related("run").order_by("-create_time")
        return [self._output(proposal) for proposal in proposals]

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

    def list_for_job(self, job_id):
        job = Job.objects.filter(id=job_id, workspace_id=self.workspace_id).first()
        if job is None:
            raise NotFound404(404, "Resource not found")
        return self._list("JOB", job_id)

    def list_for_interview(self, interview_id):
        interview = Interview.objects.filter(id=interview_id, workspace_id=self.workspace_id).first()
        if interview is None:
            raise NotFound404(404, "Resource not found")
        return self._list("INTERVIEW", interview_id)

    # ---------- 命令 ----------
    def accept(self, proposal_id, data):
        self._require_operator()
        decision_note = str(data.get("decision_note") or "").strip()[:2000]
        # 过期检测与落库在事务外执行（避免异常回滚丢失 EXPIRED 状态）
        proposal = self._proposal(proposal_id)
        if _target_stale(self.workspace_id, proposal):
            self._mark_expired(proposal)
            raise AppApiException(409, "Proposal expired: target state changed")
        with transaction.atomic():
            proposal = self._proposal(proposal_id, for_update=True)
            self._require_decision_permission(self._target(proposal), proposal)
            if proposal.status != HrAgentProposalStatus.PENDING:
                raise AppApiException(400, "Proposal is not pending")
            if _target_stale(self.workspace_id, proposal):
                # 事务内重校验：预检通过后目标可能已被并发变更
                raise AppApiException(409, "Proposal expired: target state changed")

            if proposal.target_type == "APPLICATION":
                self._execute_application_action(proposal, decision_note)
            elif proposal.target_type == "JOB" and proposal.action == HrAgentProposalAction.DRAFT:
                self._apply_job_draft(proposal)
            # INTERVIEW × DRAFT：仅确认草稿，不写任何业务状态
            proposal.status = HrAgentProposalStatus.ACCEPTED
            proposal.decided_by = self.user_id
            proposal.decided_at = timezone.now()
            proposal.decision_note = decision_note
            proposal.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "update_time"])
        write_audit_log(
            self.workspace_id, self.user_id, "AGENT_DECIDE", proposal.target_type, proposal.target_id,
            detail=f"accept {proposal.action} note={decision_note[:200]}",
            trace_id=proposal.run_id if proposal.run_id else "",
        )
        return self._output(proposal)

    def dismiss(self, proposal_id, data):
        self._require_operator()
        decision_note = str(data.get("decision_note") or "").strip()[:2000]
        with transaction.atomic():
            proposal = self._proposal(proposal_id, for_update=True)
            self._require_decision_permission(self._target(proposal), proposal)
            if proposal.status != HrAgentProposalStatus.PENDING:
                raise AppApiException(400, "Proposal is not pending")
            proposal.status = HrAgentProposalStatus.DISMISSED
            proposal.decided_by = self.user_id
            proposal.decided_at = timezone.now()
            proposal.decision_note = decision_note
            proposal.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "update_time"])
        write_audit_log(
            self.workspace_id, self.user_id, "AGENT_DECIDE", proposal.target_type, proposal.target_id,
            detail=f"dismiss {proposal.action} note={decision_note[:200]}",
            trace_id=proposal.run_id if proposal.run_id else "",
        )
        return self._output(proposal)

    # ---------- 目标解析 ----------
    def _target(self, proposal):
        if proposal.target_type == "JOB":
            return Job.objects.filter(id=proposal.target_id, workspace_id=self.workspace_id).first()
        if proposal.target_type == "INTERVIEW":
            return Interview.objects.filter(id=proposal.target_id, workspace_id=self.workspace_id).first()
        return self._target_application(proposal)

    def _mark_expired(self, proposal):
        proposal.status = HrAgentProposalStatus.EXPIRED
        proposal.save(update_fields=["status", "update_time"])

    def _execute_application_action(self, proposal, decision_note):
        application = self._target_application(proposal)
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

    def _apply_job_draft(self, proposal):
        """JD 草稿采纳：仅写入文本字段（name/description/skill_requirements），不改职位状态与关闭原因。"""
        payload = proposal.payload_json or {}
        fields = payload.get("fields") or {}
        job = Job.objects.filter(id=proposal.target_id, workspace_id=self.workspace_id).first()
        if job is None:
            raise AppApiException(409, "Proposal expired: job not found")
        update_fields = []
        name = fields.get("name")
        if isinstance(name, str) and name.strip():
            job.name = name.strip()[:128]
            update_fields.append("name")
        description = fields.get("description")
        if isinstance(description, str) and description.strip():
            job.description = description.strip()[:8000]
            update_fields.append("description")
        skills = fields.get("skill_requirements")
        if isinstance(skills, list):
            cleaned = [str(skill).strip()[:64] for skill in skills if str(skill).strip()]
            job.skill_requirements = cleaned[:30]
            update_fields.append("skill_requirements")
        if not update_fields:
            raise AppApiException(400, "JD draft has no writable fields")
        job.save(update_fields=[*update_fields, "update_time"])

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
