# coding=utf-8
"""
    @project: MaxKB
    @file： application_service.py
    @date：2026/8/17
    @desc: ATS v2 Application 命令服务（传统 ATS：JobStage + Application + ApplicationEvent）
"""
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    Application,
    ApplicationEvent,
    ApplicationEventType,
    ApplicationStatus,
    Candidate,
    CandidateStatus,
    Job,
    JobStage,
    JobStatus,
    RelationType,
    ResumeChannel,
    TerminationReason,
)
from hr.services.audit import write_audit_log

_DEFAULT_STAGES = [
    ("APPLIED", "待筛选", 1),
    ("SCREEN", "初筛", 2),
    ("INTERVIEW", "面试", 3),
    ("OFFER", "Offer", 4),
]

_ACTIVE_STATUSES = [ApplicationStatus.ACTIVE]
_TERMINAL_STATUSES = [
    ApplicationStatus.HIRED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
    ApplicationStatus.CLOSED,
]

_REJECT_REASONS = {TerminationReason.NOT_FIT, TerminationReason.SALARY, TerminationReason.OTHER}
_WITHDRAW_REASONS = {TerminationReason.CANDIDATE_WITHDRAW, TerminationReason.UNREACHABLE, TerminationReason.OTHER}
_CLOSE_REASONS = {TerminationReason.MERGED, TerminationReason.OTHER}


def create_default_stages(workspace_id, job, user_id=None):
    """给新 Job 创建默认 Pipeline（传统 ATS 的 JobStage 模板）。"""
    JobStage.objects.bulk_create([
        JobStage(
            workspace_id=workspace_id,
            job=job,
            key=key,
            name=name,
            order=order,
            is_system=True,
            user_id=user_id,
        )
        for key, name, order in _DEFAULT_STAGES
    ])


class ApplicationService:
    def __init__(self, workspace_id, user_id, hr_role):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.hr_role = hr_role

    # ---------- 权限 ----------
    def _require_operator(self):
        if self.hr_role not in ("OPERATOR", "ADMIN"):
            write_audit_log(
                self.workspace_id, self.user_id, "ACCESS_DENIED", "OTHER",
                result="DENIED", detail="Operator permission is required",
            )
            raise AppUnauthorizedFailed(403, "Operator permission is required")

    def _require_manage(self):
        if self.hr_role != "ADMIN":
            write_audit_log(
                self.workspace_id, self.user_id, "ACCESS_DENIED", "OTHER",
                result="DENIED", detail="Workspace administrator permission is required",
            )
            raise AppUnauthorizedFailed(403, "Workspace administrator permission is required")

    # ---------- 基础查询 ----------
    def _application(self, application_id, for_update=False):
        if for_update:
            application = Application.objects.select_for_update().filter(
                id=application_id, workspace_id=self.workspace_id
            ).first()
        else:
            application = Application.objects.select_related(
                "candidate", "job", "current_stage"
            ).filter(id=application_id, workspace_id=self.workspace_id).first()
        if application is None:
            raise NotFound404(404, "Resource not found")
        return application

    def _job(self, job_id):
        job = Job.objects.filter(id=job_id, workspace_id=self.workspace_id).first()
        if job is None:
            raise NotFound404(404, "Resource not found")
        return job

    def _candidate(self, candidate_id):
        candidate = Candidate.objects.filter(id=candidate_id, workspace_id=self.workspace_id).first()
        if candidate is None:
            raise NotFound404(404, "Resource not found")
        return candidate

    def _stage(self, job, stage_id):
        stage = JobStage.objects.filter(id=stage_id, workspace_id=self.workspace_id, job=job).first()
        if stage is None:
            raise AppApiException(400, "Stage does not belong to this job")
        return stage

    def _first_stage(self, job):
        return JobStage.objects.filter(workspace_id=self.workspace_id, job=job).order_by("order").first()

    # ---------- 命令 ----------
    def create_application(self, job_id, candidate_id, data):
        self._require_operator()
        job = self._job(job_id)
        candidate = self._candidate(candidate_id)
        if job.status != JobStatus.OPEN:
            raise AppApiException(400, "Job is not open")
        if candidate.status != CandidateStatus.ACTIVE:
            raise AppApiException(400, "Candidate is archived")
        if Application.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            job=job,
            status=ApplicationStatus.ACTIVE,
        ).exists():
            raise AppApiException(400, "An active application already exists")

        has_hired = Application.objects.filter(
            workspace_id=self.workspace_id, candidate=candidate, status=ApplicationStatus.HIRED
        ).exists()
        if has_hired:
            if self.hr_role != "ADMIN":
                raise AppUnauthorizedFailed(403, "Admin permission is required for rehire")
            if not data.get("rehire_confirmed") or not str(data.get("rehire_reason") or "").strip():
                raise AppApiException(400, "rehire_confirmed and rehire_reason are required")
        previous = Application.objects.filter(
            workspace_id=self.workspace_id, candidate=candidate, job=job
        ).order_by("-create_time").first()
        reapply_no = (previous.reapply_no if previous else 0) + 1
        stage = self._first_stage(job)
        if stage is None:
            raise AppApiException(400, "Job has no pipeline stages")
        try:
            with transaction.atomic():
                application = Application.objects.create(
                    workspace_id=self.workspace_id,
                    user_id=self.user_id,
                    candidate=candidate,
                    job=job,
                    current_stage=stage,
                    status=ApplicationStatus.ACTIVE,
                    relation_type=data.get("relation_type") or RelationType.APPLY,
                    channel=data.get("channel") or ResumeChannel.OTHER,
                    channel_detail=data.get("channel_detail") or "",
                    applied_at=data.get("applied_at") or timezone.now(),
                    owner_id=data.get("owner_id") or self.user_id,
                    recruiter_id=data.get("recruiter_id") or data.get("owner_id") or self.user_id,
                    reapply_of=previous,
                    reapply_no=reapply_no,
                    rehire_confirmed=bool(data.get("rehire_confirmed")),
                    rehire_reason=data.get("rehire_reason") or "",
                    note=data.get("note") or "",
                )
                self._write_event(
                    application,
                    ApplicationEventType.CREATED,
                    from_stage=None,
                    to_stage=stage,
                    from_status="",
                    to_status=ApplicationStatus.ACTIVE,
                    reason_code="",
                    reason_text=data.get("note") or "",
                    idempotency_key=data.get("idempotency_key") or str(uuid.uuid4()),
                )
        except IntegrityError as exc:
            raise AppApiException(400, "An active application already exists") from exc
        write_audit_log(self.workspace_id, self.user_id, "CREATE", "APPLICATION", application.id)
        return self._output(application)

    def move_stage(self, application_id, to_stage_id, data):
        self._require_operator()
        idempotency_key = data.get("idempotency_key") or str(uuid.uuid4())
        with transaction.atomic():
            application = self._application(application_id, for_update=True)
            if application.status != ApplicationStatus.ACTIVE:
                raise AppApiException(400, "Application is not active")
            target = self._stage(application.job, to_stage_id)
            current = application.current_stage
            if current is not None and target.order <= current.order:
                is_owner = self.user_id and self.user_id == application.owner_id
                if self.hr_role != "ADMIN" and not is_owner:
                    raise AppUnauthorizedFailed(403, "Backward or same-stage move requires owner or admin")
                if not str(data.get("reason_text") or "").strip():
                    raise AppApiException(400, "reason_text is required for backward/same-stage move")
            application.current_stage = target
            application.save(update_fields=["current_stage", "update_time"])
            self._write_event(
                application,
                ApplicationEventType.STAGE_MOVED,
                from_stage=current,
                to_stage=target,
                from_status=application.status,
                to_status=application.status,
                reason_code="",
                reason_text=data.get("reason_text") or "",
                idempotency_key=idempotency_key,
            )
        write_audit_log(
            self.workspace_id, self.user_id, "ASSIGNMENT_TRANSITION", "APPLICATION",
            application.id, detail=f"move_stage -> {target.key}",
        )
        return self._output(application)

    def _terminal(self, application_id, status, allowed_reasons, event_type, data):
        self._require_operator()
        reason = data.get("termination_reason")
        if reason not in allowed_reasons:
            raise AppApiException(400, "termination_reason is not allowed for this terminal status")
        idempotency_key = data.get("idempotency_key") or str(uuid.uuid4())
        with transaction.atomic():
            application = self._application(application_id, for_update=True)
            if application.status != ApplicationStatus.ACTIVE:
                raise AppApiException(400, "Application is not active")
            application.status = status
            application.termination_reason = reason
            application.terminated_at = timezone.now()
            application.save(update_fields=["status", "termination_reason", "terminated_at", "update_time"])
            self._write_event(
                application,
                event_type,
                from_stage=application.current_stage,
                to_stage=application.current_stage,
                from_status=ApplicationStatus.ACTIVE,
                to_status=status,
                reason_code=reason,
                reason_text=data.get("reason_text") or "",
                idempotency_key=idempotency_key,
            )
        write_audit_log(
            self.workspace_id, self.user_id, "ASSIGNMENT_TRANSITION", "APPLICATION",
            application.id, detail=f"{status} {reason}",
        )
        return self._output(application)

    def reject_application(self, application_id, data):
        return self._terminal(
            application_id, ApplicationStatus.REJECTED, _REJECT_REASONS, ApplicationEventType.REJECTED, data
        )

    def withdraw_application(self, application_id, data):
        return self._terminal(
            application_id, ApplicationStatus.WITHDRAWN, _WITHDRAW_REASONS, ApplicationEventType.WITHDRAWN, data
        )

    def close_application(self, application_id, data):
        return self._terminal(
            application_id, ApplicationStatus.CLOSED, _CLOSE_REASONS, ApplicationEventType.CLOSED, data
        )

    def restore_application(self, application_id, data):
        self._require_manage()
        reason_text = data.get("reason_text")
        if not isinstance(reason_text, str) or not reason_text.strip():
            raise AppApiException(400, "restore reason is required")
        idempotency_key = data.get("idempotency_key") or str(uuid.uuid4())
        with transaction.atomic():
            application = self._application(application_id, for_update=True)
            if application.status != ApplicationStatus.REJECTED:
                raise AppApiException(400, "Only rejected application can be restored")
            if Application.objects.filter(
                workspace_id=self.workspace_id,
                candidate=application.candidate,
                job=application.job,
                status=ApplicationStatus.ACTIVE,
            ).exclude(id=application.id).exists():
                raise AppApiException(400, "An active application already exists")
            application.status = ApplicationStatus.ACTIVE
            application.termination_reason = None
            application.terminated_at = None
            application.save(update_fields=["status", "termination_reason", "terminated_at", "update_time"])
            self._write_event(
                application,
                ApplicationEventType.RESTORED,
                from_stage=application.current_stage,
                to_stage=application.current_stage,
                from_status=ApplicationStatus.REJECTED,
                to_status=ApplicationStatus.ACTIVE,
                reason_code="",
                reason_text=reason_text,
                idempotency_key=idempotency_key,
            )
        write_audit_log(
            self.workspace_id, self.user_id, "RESTORE", "APPLICATION",
            application.id, detail=reason_text,
        )
        return self._output(application)

    # ---------- 查询 ----------
    def page_applications(self, current_page, page_size, query):
        queryset = Application.objects.filter(workspace_id=self.workspace_id).select_related(
            "candidate", "job", "current_stage"
        )
        owner_id = query.get("owner_id")
        if owner_id:
            queryset = queryset.filter(owner_id=owner_id)
        status = query.get("status")
        if status:
            queryset = queryset.filter(status=status)
        job_id = query.get("job_id")
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        stage_id = query.get("stage_id")
        if stage_id:
            queryset = queryset.filter(current_stage_id=stage_id)
        total = queryset.count()
        start = (current_page - 1) * page_size
        records = queryset.order_by("-update_time")[start:start + page_size]
        return {"total": total, "records": [self._output(app) for app in records]}

    def list_events(self, application_id):
        application = self._application(application_id)
        events = ApplicationEvent.objects.filter(
            workspace_id=self.workspace_id, application=application
        ).order_by("create_time")
        return [self._event_output(event) for event in events]

    # ---------- 内部 ----------
    def _write_event(self, application, event_type, from_stage, to_stage, from_status, to_status,
                     reason_code, reason_text, idempotency_key):
        event, created = ApplicationEvent.objects.get_or_create(
            workspace_id=self.workspace_id,
            application=application,
            event_type=event_type,
            idempotency_key=idempotency_key,
            defaults={
                "from_stage": from_stage,
                "to_stage": to_stage,
                "from_status": from_status,
                "to_status": to_status,
                "actor_id": self.user_id,
                "reason_code": reason_code,
                "reason_text": reason_text,
                "trace_id": "",
            },
        )
        return event

    @staticmethod
    def _output(application):
        return {
            "id": str(application.id),
            "candidate_id": str(application.candidate_id),
            "job_id": str(application.job_id),
            "candidate_name": application.candidate.name,
            "job_name": application.job.name,
            "current_stage": {
                "id": str(application.current_stage.id),
                "key": application.current_stage.key,
                "name": application.current_stage.name,
                "order": application.current_stage.order,
            } if application.current_stage else None,
            "status": application.status,
            "relation_type": application.relation_type,
            "channel": application.channel,
            "channel_detail": application.channel_detail,
            "applied_at": application.applied_at,
            "owner_id": str(application.owner_id) if application.owner_id else None,
            "recruiter_id": str(application.recruiter_id) if application.recruiter_id else None,
            "termination_reason": application.termination_reason,
            "terminated_at": application.terminated_at,
            "reapply_no": application.reapply_no,
            "rehire_confirmed": application.rehire_confirmed,
            "note": application.note,
            "create_time": application.create_time,
            "update_time": application.update_time,
        }

    @staticmethod
    def _event_output(event):
        return {
            "id": str(event.id),
            "application_id": str(event.application_id),
            "event_type": event.event_type,
            "from_stage_id": str(event.from_stage_id) if event.from_stage_id else None,
            "to_stage_id": str(event.to_stage_id) if event.to_stage_id else None,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "reason_code": event.reason_code,
            "reason_text": event.reason_text,
            "create_time": event.create_time,
        }
