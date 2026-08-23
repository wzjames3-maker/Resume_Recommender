import uuid_utils.compat as uuid
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from common.exception.app_exception import AppApiException, NotFound404
from hr.models import Interview, InterviewStatus
from hr.services.application_service import normalize_interview_datetime, validate_interview_times
from hr.services.audit import write_audit_log
from users.models.user import User

# P2-16: 面试状态迁移矩阵（update_interview 用）：仅列出的 status→status 迁移合法；
# 同状态提交视为空操作放行；PASSED/FAILED/NO_SHOW 为终态不可再流转；CANCELLED 仅可重开回 PENDING。
_INTERVIEW_STATUS_TRANSITIONS = {
    InterviewStatus.PENDING: {
        InterviewStatus.PASSED,
        InterviewStatus.FAILED,
        InterviewStatus.NO_SHOW,
        InterviewStatus.CANCELLED,
    },
    InterviewStatus.CANCELLED: {InterviewStatus.PENDING},
}


class InterviewMixin:
    """面试领域：面试官指派校验、面试更新/全局列表/我的面试/反馈提交。"""

    def _interviewer_user_id(self, data):
        value = data.get("interviewer_user_id")
        if value in (None, ""):
            return None
        try:
            user_id = uuid.UUID(str(value))
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "interviewer_user_id is invalid") from exc
        # 校验基于 User 表存在性而非 hr_members 列表（防枚举的列表受限，需允许首次指派）
        import uuid_utils.compat as _uuid

        from users.models import User

        _KERNEL_SYSTEM_USER_ID = _uuid.UUID("f0dd8f71-e4ee-11ee-8c84-a8a1595801ab")
        if user_id == _KERNEL_SYSTEM_USER_ID:
            raise AppApiException(400, "User is not a workspace member")
        user = User.objects.filter(id=user_id, is_active=True).first()
        if not user:
            raise AppApiException(400, "User is not a workspace member")
        from common.constants.permission_constants import RoleConstants

        if user.role == RoleConstants.ADMIN.name:
            raise AppApiException(400, "User is not a workspace member")
        return user_id

    @staticmethod
    def _user_nick_name(user_id):
        if user_id is None:
            return ""
        user = User.objects.filter(id=user_id).only("nick_name").first()
        return user.nick_name if user else ""

    @staticmethod
    def _interview_output(interview):
        return {
            "id": str(interview.id),
            "assignment_id": None,
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

    def update_interview(self, interview_id, data):
        self._require_operator()
        interview = Interview.objects.filter(id=interview_id, workspace_id=self.workspace_id).first()
        if interview is None:
            raise NotFound404(404, "Resource not found")
        # P2-16: 记录变更前快照，用于审计（只记字段名与状态迁移，不记字段值，防 PII 入审计）
        tracked_fields = ("status", "feedback", "interviewer", "interviewer_user_id", "feedback_deadline", "scheduled_at")
        before = {field: getattr(interview, field) for field in tracked_fields}
        original_status = interview.status
        if "status" in data:
            if data["status"] not in InterviewStatus.values:
                raise AppApiException(400, "status is invalid")
            if data["status"] != interview.status and data["status"] not in _INTERVIEW_STATUS_TRANSITIONS.get(
                interview.status, set()
            ):
                raise AppApiException(400, "status transition is not allowed")
            interview.status = data["status"]
        if "feedback" in data:
            interview.feedback = self._optional_string(data, "feedback", 4096)
        if "interviewer" in data:
            interview.interviewer = self._optional_string(data, "interviewer", 64)
        if "interviewer_user_id" in data:
            interviewer_user_id = self._interviewer_user_id(data)
            interview.interviewer_user_id = interviewer_user_id
            if data.get("interviewer") is None:
                interview.interviewer = self._user_nick_name(interviewer_user_id)
        # P3: 时间字段入口校验：非法时间串 400（防入库/解析 500），且 deadline 必须晚于开始时间
        if "scheduled_at" in data or "feedback_deadline" in data:
            interview.scheduled_at = normalize_interview_datetime(
                data.get("scheduled_at", interview.scheduled_at), "scheduled_at"
            )
            interview.feedback_deadline = normalize_interview_datetime(
                data.get("feedback_deadline", interview.feedback_deadline), "feedback_deadline"
            )
            validate_interview_times(interview.scheduled_at, interview.feedback_deadline)
        changed_fields = [field for field in tracked_fields if getattr(interview, field) != before[field]]
        interview.save()
        write_audit_log(
            self.workspace_id, self.user_id, "UPDATE", "INTERVIEW", interview.id,
            detail={"changed_fields": changed_fields, "status_from": original_status, "status_to": interview.status},
        )
        return self._interview_output(interview)

    def list_interviews(self, params):
        """HR 全局面试列表（OPERATOR+）：按状态/候选人/职位/面试官筛选，分页返回。"""
        try:
            current_page = max(1, int(params.get("current_page", 1)))
            page_size = min(100, max(1, int(params.get("page_size", 20))))
        except (TypeError, ValueError) as exc:
            raise AppApiException(400, "current_page and page_size must be integers") from exc
        queryset = (
            Interview.objects.filter(workspace_id=self.workspace_id)
            .select_related("application__candidate", "application__job")
            .order_by("-scheduled_at")
        )
        status = params.get("status")
        if status:
            if status not in InterviewStatus.values:
                raise AppApiException(400, "status is invalid")
            queryset = queryset.filter(status=status)
        search = str(params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(application__candidate__name__icontains=search)
                | Q(application__job__name__icontains=search)
                | Q(interviewer__icontains=search)
            )
        interviewer = str(params.get("interviewer") or "").strip()
        if interviewer:
            queryset = queryset.filter(interviewer__icontains=interviewer)
        overdue = params.get("overdue")
        if overdue in ("1", "true", "True"):
            now = timezone.now()
            queryset = queryset.filter(
                status=InterviewStatus.PENDING, feedback_deadline__lt=now
            )
        total = queryset.count()
        start = (current_page - 1) * page_size
        records = []
        now = timezone.now()
        for interview in queryset[start:start + page_size]:
            application = interview.application
            is_overdue = (
                interview.status == InterviewStatus.PENDING
                and interview.feedback_deadline is not None
                and interview.feedback_deadline < now
            )
            records.append({
                "interview_id": str(interview.id),
                "application_id": str(interview.application_id) if interview.application_id else None,
                "candidate_id": str(application.candidate_id) if application else None,
                "candidate_name": application.candidate.name if application else "",
                "job_id": str(application.job_id) if application else None,
                "job_name": application.job.name if application else "",
                "round_no": interview.round_no,
                "interviewer": interview.interviewer,
                "scheduled_at": interview.scheduled_at,
                "status": interview.status,
                "is_overdue": is_overdue,
                "feedback_deadline": interview.feedback_deadline,
                "feedback_submitted_at": interview.feedback_submitted_at,
                "feedback": interview.feedback,
                "create_time": interview.create_time,
            })
        return {"total": total, "records": records, "current_page": current_page, "page_size": page_size}

    def list_my_interviews(self):
        """面试官视角：仅返回本人被指派的面试，最小字段（不含 PII/简历/技能）。"""
        interviews = (
            Interview.objects.filter(workspace_id=self.workspace_id, interviewer_user_id=self.user_id)
            .select_related("application__job", "application__candidate")
            .order_by("-scheduled_at")
        )
        now = timezone.now()
        records = []
        for interview in interviews:
            overdue = (
                interview.status == InterviewStatus.PENDING
                and interview.feedback_deadline is not None
                and interview.feedback_deadline < now
            )
            application = interview.application
            candidate_name = application.candidate.name if application is not None else ""
            job_name = application.job.name if application is not None else ""
            records.append({
                "interview_id": str(interview.id),
                "assignment_id": None,
                "application_id": str(interview.application_id) if interview.application_id else None,
                "round_no": interview.round_no,
                "scheduled_at": interview.scheduled_at,
                "status": interview.status,
                "feedback": interview.feedback,
                "feedback_deadline": interview.feedback_deadline,
                "feedback_submitted_at": interview.feedback_submitted_at,
                "is_overdue": overdue,
                "candidate_name": candidate_name,
                "job_name": job_name,
            })
        return records

    def submit_interview_feedback(self, interview_id, data):
        """面试官本人提交反馈；非本人一律 404；已提交过则拒绝（幂等防翻转）；写时间戳并审计。"""
        already_submitted = False
        with transaction.atomic():
            # P2-16: 行锁 + 已提交检查，防止并发重复提交翻转已记录的面试结论
            interview = (
                Interview.objects.select_for_update()
                .filter(id=interview_id, workspace_id=self.workspace_id)
                .first()
            )
            if interview is None or interview.interviewer_user_id != self.user_id:
                raise NotFound404(404, "Resource not found")
            already_submitted = interview.feedback_submitted_at is not None
            if not already_submitted:
                status = data.get("status")
                if status not in (InterviewStatus.PASSED, InterviewStatus.FAILED, InterviewStatus.NO_SHOW):
                    raise AppApiException(400, "status is invalid")
                interview.status = status
                interview.feedback = self._optional_string(data, "feedback", 4096)
                interview.feedback_submitted_at = timezone.now()
                interview.save(update_fields=["status", "feedback", "feedback_submitted_at", "update_time"])
                # P2-16: 审计不落反馈正文（自由文本可能含候选人 PII），仅记录结论状态与轮次
                write_audit_log(
                    self.workspace_id, self.user_id, "INTERVIEW_FEEDBACK", "INTERVIEW", interview.id,
                    detail={"status": status, "round_no": interview.round_no},
                )
        if already_submitted:
            # 重复提交留痕（事务外写审计，避免随回滚丢失）
            write_audit_log(
                self.workspace_id, self.user_id, "INTERVIEW_FEEDBACK", "INTERVIEW", interview.id,
                result="FAILED", detail="feedback already submitted",
            )
            raise AppApiException(400, "feedback has already been submitted")
        return self._interview_output(interview)
