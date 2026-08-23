import logging
from datetime import datetime

import uuid_utils.compat as uuid

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    Candidate,
    Job,
    RelationType,
    ResumeChannel,
)
from hr.services.audit import write_audit_log

logger = logging.getLogger("hr")

CANDIDATE_EXPORT_FIELDS = [
    "name",
    "status",
    "create_time",
]


class RecruitmentServiceBase:
    """招聘域服务公共基座：构造器与跨领域复用的鉴权/校验/脱敏等辅助方法。"""

    def __init__(self, workspace_id, user_id, hr_role):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.hr_role = hr_role

    def _candidate(self, candidate_id):
        candidate = Candidate.objects.filter(id=candidate_id, workspace_id=self.workspace_id).first()
        if candidate is None:
            raise NotFound404(404, "Resource not found")
        return candidate

    def _job(self, job_id):
        job = Job.objects.filter(id=job_id, workspace_id=self.workspace_id).first()
        if job is None:
            raise NotFound404(404, "Resource not found")
        return job

    @staticmethod
    def _masked_phone(phone):
        if not phone or len(phone) <= 7:
            return phone
        return f"{phone[:3]}****{phone[-4:]}"

    @staticmethod
    def _masked_email(email):
        if not email or "@" not in email:
            return email
        local, _, domain = email.partition("@")
        return f"{local[:2]}***@{domain}"

    def _require_manage(self):
        if self.hr_role != "ADMIN":
            write_audit_log(
                self.workspace_id, self.user_id, "ACCESS_DENIED", "OTHER",
                result="DENIED", detail="Workspace administrator permission is required",
            )
            raise AppUnauthorizedFailed(403, "Workspace administrator permission is required")

    def _require_operator(self):
        if self.hr_role not in ("OPERATOR", "ADMIN"):
            write_audit_log(
                self.workspace_id, self.user_id, "ACCESS_DENIED", "OTHER",
                result="DENIED", detail="Operator permission is required",
            )
            raise AppUnauthorizedFailed(403, "Operator permission is required")

    @staticmethod
    def _required_string(data, field, maximum):
        value = data.get(field, "")
        if not isinstance(value, str) or not value.strip():
            raise AppApiException(400, f"{field} is required")
        if len(value.strip()) > maximum:
            raise AppApiException(400, f"{field} is too long")
        return value.strip()

    @staticmethod
    def _optional_string(data, field, maximum):
        value = data.get(field, "")
        if value is None:
            return ""
        if not isinstance(value, str) or len(value.strip()) > maximum:
            raise AppApiException(400, f"{field} is invalid")
        return value.strip()

    @staticmethod
    def _owner_id(data):
        value = data.get("owner_id")
        if value in (None, ""):
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "owner_id is invalid") from exc

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
