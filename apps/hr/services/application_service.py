# coding=utf-8
"""
    @project: MaxKB
    @file： application_service.py
    @date：2026/8/17
    @desc: ATS v2 Application 命令服务（传统 ATS：JobStage + Application + ApplicationEvent）
"""
import uuid
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    Application,
    ApplicationEvent,
    ApplicationEventType,
    ApplicationStatus,
    Candidate,
    CandidateStatus,
    Interview,
    Job,
    JobCloseReason,
    JobStage,
    JobStatus,
    Offer,
    OfferStatus,
    RelationType,
    ResumeChannel,
    TerminationReason,
)
from hr.services.audit import write_audit_log
from users.models import User

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

# Offer 接受的系统终态：由 Offer accept 同事务触发 Application → HIRED（§2.1）
_OFFER_STAGE_KEY = "OFFER"
_INTERVIEW_STAGE_KEYS = ("SCREEN", "INTERVIEW")


def write_application_event(workspace_id, actor_id, application, event_type, from_stage, to_stage,
                            from_status, to_status, reason_code, reason_text, idempotency_key):
    """写一条不可变流程账本事件；同 (application, event_type, idempotency_key) 幂等。"""
    event, created = ApplicationEvent.objects.get_or_create(
        workspace_id=workspace_id,
        application=application,
        event_type=event_type,
        idempotency_key=idempotency_key,
        defaults={
            "from_stage": from_stage,
            "to_stage": to_stage,
            "from_status": from_status,
            "to_status": to_status,
            "actor_id": actor_id,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "trace_id": "",
        },
    )
    return event


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

    def _interviewer_user_id(self, data):
        value = data.get("interviewer_user_id")
        if value in (None, ""):
            return None
        try:
            user_id = uuid.UUID(str(value))
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "interviewer_user_id is invalid") from exc
        from hr.serializers.access import hr_members

        member_ids = {member["id"] for member in hr_members(self.workspace_id)}
        if user_id not in member_ids:
            raise AppApiException(400, "User is not a workspace member")
        return user_id

    @staticmethod
    def _optional_string(data, field, maximum):
        value = data.get(field, "")
        if value is None:
            return ""
        if not isinstance(value, str) or len(value.strip()) > maximum:
            raise AppApiException(400, f"{field} is invalid")
        return value.strip()

    @staticmethod
    def _user_nick_name(user_id):
        if user_id is None:
            return ""
        user = User.objects.filter(id=user_id).only("nick_name").first()
        return user.nick_name if user else ""

    @staticmethod
    def _relation_type(data):
        value = data.get("relation_type", RelationType.APPLY)
        if value not in RelationType.values:
            raise AppApiException(400, "relation_type is invalid")
        return value

    @staticmethod
    def _channel(data):
        value = data.get("channel", ResumeChannel.OTHER)
        if value not in ResumeChannel.values:
            raise AppApiException(400, "channel is invalid")
        return value

    @staticmethod
    def _applied_at(data):
        value = data.get("applied_at")
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise AppApiException(400, "applied_at is invalid") from exc

    @staticmethod
    def _uuid_field(data, field):
        value = data.get(field)
        if value in (None, ""):
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, f"{field} is invalid") from exc

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
        owner_id = self._uuid_field(data, "owner_id") or self.user_id
        recruiter_id = self._uuid_field(data, "recruiter_id") or owner_id
        try:
            with transaction.atomic():
                application = Application.objects.create(
                    workspace_id=self.workspace_id,
                    user_id=self.user_id,
                    candidate=candidate,
                    job=job,
                    current_stage=stage,
                    status=ApplicationStatus.ACTIVE,
                    relation_type=self._relation_type(data),
                    channel=self._channel(data),
                    channel_detail=self._optional_string(data, "channel_detail", 128),
                    applied_at=self._applied_at(data) or timezone.now(),
                    owner_id=owner_id,
                    recruiter_id=recruiter_id,
                    reapply_of=previous,
                    reapply_no=reapply_no,
                    rehire_confirmed=bool(data.get("rehire_confirmed")),
                    rehire_reason=self._optional_string(data, "rehire_reason", 4096),
                    note=self._optional_string(data, "note", 4096),
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
            existing_event = ApplicationEvent.objects.filter(
                workspace_id=self.workspace_id,
                application=application,
                event_type=ApplicationEventType.STAGE_MOVED,
                idempotency_key=idempotency_key,
            ).first()
            if existing_event is not None:
                return self._output(application)
            if application.status != ApplicationStatus.ACTIVE:
                raise AppApiException(400, "Application is not active")
            target = self._stage(application.job, to_stage_id)
            current = application.current_stage
            # §2.2：默认只允许按 order 前移一位；回退/同阶段/跳级必须 owner 或 ADMIN，且写 reason_text
            if current is not None and (target.order <= current.order or target.order > current.order + 1):
                is_owner = self.user_id and self.user_id == application.owner_id
                if self.hr_role != "ADMIN" and not is_owner:
                    raise AppUnauthorizedFailed(403, "Backward or skip move requires owner or admin")
                if not str(data.get("reason_text") or "").strip():
                    raise AppApiException(400, "reason_text is required for backward or skip move")
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
            existing_event = ApplicationEvent.objects.filter(
                workspace_id=self.workspace_id,
                application=application,
                event_type=event_type,
                idempotency_key=idempotency_key,
            ).first()
            if existing_event is not None:
                return self._output(application)
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

    # ---------- Job 两阶段关闭（R2） ----------
    def close_preview(self, job_id):
        """关闭前预览：返回该职位全部 ACTIVE Application（供 STRICT/BULK 决策）。"""
        job = self._job(job_id)
        applications = Application.objects.filter(
            workspace_id=self.workspace_id,
            job=job,
            status=ApplicationStatus.ACTIVE,
        ).select_related("candidate", "current_stage").order_by("create_time")
        records = [
            {
                "application_id": str(application.id),
                "candidate_name": application.candidate.name,
                "current_stage": application.current_stage.key if application.current_stage else "",
                "owner_id": str(application.owner_id) if application.owner_id else None,
            }
            for application in applications
        ]
        return {
            "job_id": str(job.id),
            "job_status": job.status,
            "active_application_count": len(records),
            "applications": records,
        }

    def close_job(self, job_id, data):
        """两阶段关闭：STRICT 有 ACTIVE 时 409；BULK 必须显式确认。

        每条 ACTIVE Application → CLOSED + JOB_CLOSED + 写事件（确定性幂等键）；
        该 Application 下 DRAFT/SENT Offer 自动 WITHDRAWN；legacy 指派同步收尾。
        """
        self._require_manage()
        job = self._job(job_id)
        reason = data.get("close_reason")
        if reason not in JobCloseReason.values:
            raise AppApiException(400, "close_reason is invalid")
        mode = data.get("mode", "STRICT")
        if mode not in ("STRICT", "BULK"):
            raise AppApiException(400, "mode must be STRICT|BULK")
        with transaction.atomic():
            job = Job.objects.select_for_update().get(id=job.id)
            active = list(
                Application.objects.select_for_update().filter(
                    workspace_id=self.workspace_id,
                    job=job,
                    status=ApplicationStatus.ACTIVE,
                )
            )
            if active and mode == "STRICT":
                raise AppApiException(409, "Job has active applications; use BULK mode with bulk_confirmed=true")
            if mode == "BULK" and not data.get("bulk_confirmed"):
                raise AppApiException(400, "bulk_confirmed=true is required in BULK mode")
            job.status = JobStatus.CLOSED
            job.close_reason = reason
            job.save(update_fields=["status", "close_reason", "update_time"])
            for application in active:
                application.status = ApplicationStatus.CLOSED
                application.termination_reason = TerminationReason.JOB_CLOSED
                application.terminated_at = timezone.now()
                application.save(update_fields=["status", "termination_reason", "terminated_at", "update_time"])
                self._write_event(
                    application,
                    ApplicationEventType.CLOSED,
                    from_stage=application.current_stage,
                    to_stage=application.current_stage,
                    from_status=ApplicationStatus.ACTIVE,
                    to_status=ApplicationStatus.CLOSED,
                    reason_code=TerminationReason.JOB_CLOSED,
                    reason_text=f"job closed: {reason}",
                    idempotency_key=f"job_close:{job.id}:{application.id}",
                )
            withdrawn_offers = Offer.objects.filter(
                workspace_id=self.workspace_id,
                application__job=job,
                status__in=[OfferStatus.DRAFT, OfferStatus.SENT],
            ).update(status=OfferStatus.WITHDRAWN, withdrawn_at=timezone.now(), update_time=timezone.now())
        write_audit_log(
            self.workspace_id, self.user_id, "JOB_CLOSE", "JOB", job.id,
            detail=f"{reason} mode={mode} closed={len(active)} offers={withdrawn_offers}",
        )
        return {
            "job_id": str(job.id),
            "closed_count": len(active),
            "withdrawn_offer_count": withdrawn_offers,
        }

    # ---------- Interview（R3：挂 Application） ----------
    def create_interview(self, application_id, data):
        """Interview 创建守卫：Application ACTIVE 且当前 Stage 为 SCREEN/INTERVIEW；round_no 服务端生成。"""
        self._require_operator()
        application = self._application(application_id)
        if application.status != ApplicationStatus.ACTIVE:
            raise AppApiException(400, "Application is not active")
        if application.current_stage is None or application.current_stage.key not in _INTERVIEW_STAGE_KEYS:
            raise AppApiException(400, "Interview can only be created at SCREEN or INTERVIEW stage")
        interviewer_user_id = self._interviewer_user_id(data)
        max_round = Interview.objects.filter(
            workspace_id=self.workspace_id,
            application=application,
        ).aggregate(max_round=Max("round_no"))["max_round"] or 0
        try:
            interview = Interview.objects.create(
                workspace_id=self.workspace_id,
                application=application,
                round_no=max_round + 1,
                interviewer=self._optional_string(data, "interviewer", 64) or self._user_nick_name(interviewer_user_id),
                interviewer_user_id=interviewer_user_id,
                feedback_deadline=data.get("feedback_deadline") or None,
                scheduled_at=data.get("scheduled_at") or None,
                user_id=self.user_id,
            )
        except IntegrityError as exc:
            raise AppApiException(400, "Interview round already exists") from exc
        write_audit_log(
            self.workspace_id, self.user_id, "CREATE", "INTERVIEW",
            interview.id, detail=f"round {interview.round_no}",
        )
        return self._interview_output(interview)

    def list_interviews(self, application_id):
        application = self._application(application_id)
        interviews = Interview.objects.filter(
            workspace_id=self.workspace_id,
            application=application,
        ).order_by("round_no")
        return [self._interview_output(interview) for interview in interviews]

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
        channel = query.get("channel")
        if channel:
            queryset = queryset.filter(channel=channel)
        relation_type = query.get("relation_type")
        if relation_type:
            queryset = queryset.filter(relation_type=relation_type)
        city = query.get("city")
        if city:
            queryset = queryset.filter(
                Q(candidate__current_city__icontains=city) | Q(candidate__target_city__icontains=city)
            )
        q = query.get("q")
        if q:
            queryset = queryset.filter(
                Q(candidate__name__icontains=q)
                | Q(candidate__phone__icontains=q)
                | Q(candidate__email__icontains=q)
            )
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
        return write_application_event(
            self.workspace_id, self.user_id, application, event_type, from_stage, to_stage,
            from_status, to_status, reason_code, reason_text, idempotency_key,
        )

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

    def _interview_output(self, interview):
        return {
            "id": str(interview.id),
            "application_id": str(interview.application_id) if interview.application_id else None,
            "round_no": interview.round_no,
            "interviewer": interview.interviewer,
            "interviewer_user_id": str(interview.interviewer_user_id) if interview.interviewer_user_id else None,
            "feedback_deadline": interview.feedback_deadline,
            "feedback_submitted_at": interview.feedback_submitted_at,
            "scheduled_at": interview.scheduled_at,
            "status": interview.status,
            "feedback": interview.feedback,
            "create_time": interview.create_time,
            "update_time": interview.update_time,
        }

    def _event_output(self, event):
        is_viewer = self.hr_role == "VIEWER"
        return {
            "id": str(event.id),
            "application_id": str(event.application_id),
            "event_type": event.event_type,
            "from_stage_id": str(event.from_stage_id) if event.from_stage_id else None,
            "to_stage_id": str(event.to_stage_id) if event.to_stage_id else None,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "actor_id": None if is_viewer else (str(event.actor_id) if event.actor_id else None),
            "reason_code": event.reason_code,
            "reason_text": "" if is_viewer else event.reason_text,
            "create_time": event.create_time,
        }
