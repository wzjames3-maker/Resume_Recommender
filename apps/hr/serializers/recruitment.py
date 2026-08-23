import hashlib
import os
import tempfile
from datetime import datetime
from functools import reduce
from operator import or_

import uuid_utils.compat as uuid
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from celery_once import AlreadyQueued
from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    Application,
    ApplicationStatus,
    HrAgentProposal,
    Candidate,
    CandidateStatus,
    Interview,
    InterviewStatus,
    Job,
    JobCloseReason,
    JobStatus,
    Offer,
    OnboardingHandoff,
    RelationType,
    ResumeChannel,
    ResumeDatabase,
    ResumeDatabaseMembership,
    ResumeDatabaseStatus,
    ResumeFile,
    ResumeStatus,
    TerminationReason,
)
from hr.services.flow_log import delete_flow_logs, log_flow
from hr.services.resume_index import delete_resume_index, set_resume_index_active
from hr.services.resume_parser import extract_text_from_docx, extract_text_from_txt
from hr.services.audit import write_audit_log
from hr.services.application_service import (
    create_default_stages,
    normalize_interview_datetime,
    validate_interview_times,
)
from hr.services.storage import get_storage
from hr.task.resume import parse_resume_task
from users.models.user import User

CANDIDATE_EXPORT_FIELDS = [
    "name",
    "status",
    "create_time",
]

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


class RecruitmentService:
    def __init__(self, workspace_id, user_id, hr_role):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.hr_role = hr_role

    def _candidate(self, candidate_id):
        candidate = Candidate.objects.filter(id=candidate_id, workspace_id=self.workspace_id).first()
        if candidate is None:
            raise NotFound404(404, "Resource not found")
        return candidate

    def _resume_database(self, database_id, active_only=True):
        try:
            database_uuid = uuid.UUID(str(database_id))
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "resume_database_id is invalid") from exc
        queryset = ResumeDatabase.objects.filter(id=database_uuid, workspace_id=self.workspace_id)
        if active_only:
            queryset = queryset.filter(status=ResumeDatabaseStatus.ACTIVE)
        database = queryset.first()
        if database is None:
            raise NotFound404(404, "Resume database not found")
        return database

    def _default_resume_database(self):
        database = ResumeDatabase.objects.filter(
            workspace_id=self.workspace_id, status=ResumeDatabaseStatus.ACTIVE, is_system=True
        ).first()
        if database is None:
            database = ResumeDatabase.objects.filter(
                workspace_id=self.workspace_id, status=ResumeDatabaseStatus.ACTIVE, is_default=True
            ).first()
        if database is None:
            database = ResumeDatabase.objects.create(
                workspace_id=self.workspace_id, name="总库", is_default=True, is_system=True, user_id=self.user_id
            )
        elif not database.is_system:
            database.is_system = True
            if database.name == "默认简历库":
                database.name = "总库"
            database.save(update_fields=["is_system", "name", "update_time"])
        return database

    def _resume_databases(self, database_ids=None, include_total=True):
        if database_ids is None:
            requested_ids = []
        elif isinstance(database_ids, str):
            requested_ids = [value.strip() for value in database_ids.split(",") if value.strip()]
        elif isinstance(database_ids, (list, tuple, set)):
            requested_ids = [str(value).strip() for value in database_ids if str(value).strip()]
        else:
            raise AppApiException(400, "resume_database_ids must be an array")
        databases = []
        seen = set()
        if include_total:
            total = self._default_resume_database()
            databases.append(total)
            seen.add(str(total.id))
        for database_id in requested_ids:
            database = self._resume_database(database_id)
            if str(database.id) not in seen:
                databases.append(database)
                seen.add(str(database.id))
        if not databases and include_total:
            databases.append(self._default_resume_database())
        return databases

    @staticmethod
    def _attach_resume_databases(resume, databases):
        ResumeDatabaseMembership.objects.bulk_create(
            [ResumeDatabaseMembership(resume_file=resume, resume_database=database) for database in databases],
            ignore_conflicts=True,
        )

    @staticmethod
    def _resume_database_output(database):
        return {
            "id": str(database.id),
            "name": database.name,
            "description": database.description,
            "status": database.status,
            "is_default": database.is_default,
            "is_system": database.is_system,
            "resume_count": getattr(database, "resume_count", database.resume_memberships.count()),
            "candidate_count": getattr(database, "candidate_count", database.resume_memberships.values("resume_file__candidate_id").distinct().count()),
            "pending_count": getattr(database, "pending_count", database.resume_memberships.filter(resume_file__status=ResumeStatus.PENDING).count()),
            "create_time": database.create_time,
            "update_time": database.update_time,
        }

    def list_resume_databases(self):
        self._default_resume_database()
        databases = ResumeDatabase.objects.filter(workspace_id=self.workspace_id).annotate(
            resume_count=Count("resume_memberships__resume_file", distinct=True),
            candidate_count=Count("resume_memberships__resume_file__candidate", distinct=True),
            pending_count=Count("resume_memberships__resume_file", filter=Q(resume_memberships__resume_file__status=ResumeStatus.PENDING), distinct=True),
        ).order_by("-is_system", "-is_default", "create_time")
        return [self._resume_database_output(database) for database in databases]

    def create_resume_database(self, data):
        self._require_manage()
        name = self._required_string(data, "name", 128)
        if ResumeDatabase.objects.filter(workspace_id=self.workspace_id, name=name).exists():
            raise AppApiException(400, "同名简历库已存在")
        description = self._optional_string(data, "description", 512)
        database = ResumeDatabase.objects.create(
            workspace_id=self.workspace_id, name=name, description=description, is_default=False, is_system=False, user_id=self.user_id
        )
        write_audit_log(self.workspace_id, self.user_id, "CREATE", "OTHER", database.id, detail="resume database created")
        return self._resume_database_output(database)

    def archive_resume_database(self, database_id):
        self._require_manage()
        database = self._resume_database(database_id, active_only=False)
        if database.is_system or database.is_default:
            raise AppApiException(400, "总库不能归档")
        if database.status == ResumeDatabaseStatus.ARCHIVED:
            return self._resume_database_output(database)
        database.status = ResumeDatabaseStatus.ARCHIVED
        database.save(update_fields=["status", "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "ARCHIVE", "OTHER", database.id, detail="resume database archived")
        return self._resume_database_output(database)

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
    def _skill_requirements(data):
        value = data.get("skill_requirements", [])
        if not isinstance(value, list) or any(not isinstance(skill, str) or not skill.strip() for skill in value):
            raise AppApiException(400, "skill_requirements must be a list of non-empty strings")
        return [skill.strip() for skill in value]

    @staticmethod
    def _owner_id(data):
        value = data.get("owner_id")
        if value in (None, ""):
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "owner_id is invalid") from exc

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
    def _close_reason(data):
        value = data.get("close_reason")
        if not value:
            raise AppApiException(400, "close_reason is required")
        if value not in JobCloseReason.values:
            raise AppApiException(400, "close_reason is invalid")
        return value

    @staticmethod
    def _termination_reason(data):
        value = data.get("termination_reason")
        if not value:
            raise AppApiException(400, "termination_reason is required")
        if value not in TerminationReason.values:
            raise AppApiException(400, "termination_reason is invalid")
        return value

    def _candidate_output(self, candidate):
        masked = self.hr_role == "VIEWER"
        return {
            "id": str(candidate.id),
            "name": candidate.name,
            "email": self._masked_email(candidate.email) if masked else candidate.email,
            "phone": self._masked_phone(candidate.phone) if masked else candidate.phone,
            "status": candidate.status,
            "create_time": candidate.create_time,
            "update_time": candidate.update_time,
        }

    @staticmethod
    def _job_output(job):
        return {
            "id": str(job.id),
            "name": job.name,
            "department": job.department,
            "city": job.city,
            "level": job.level,
            "headcount": job.headcount,
            "description": job.description,
            "skill_requirements": job.skill_requirements,
            "status": job.status,
            "close_reason": job.close_reason,
            "owner_id": str(job.owner_id) if job.owner_id else None,
            "active_assignment_count": getattr(job, "active_assignment_count", 0),
            "create_time": job.create_time,
            "update_time": job.update_time,
        }

    def create_candidate(self, data):
        self._require_operator()
        candidate = Candidate.objects.create(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            name=self._required_string(data, "name", 128),
            email=data.get("email") or None,
            phone=self._optional_string(data, "phone", 20),
        )
        write_audit_log(self.workspace_id, self.user_id, "CREATE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    def _filter_candidates(self, query):
        queryset = Candidate.objects.filter(workspace_id=self.workspace_id)
        name = query.get("name")
        status = query.get("status")
        skills = query.get("skills")
        resume_database_ids = query.getlist("resume_database_ids") if hasattr(query, "getlist") else []
        if not resume_database_ids:
            resume_database_ids = query.get("resume_database_ids") or query.get("resume_database_id")
        if resume_database_ids:
            databases = self._resume_databases(resume_database_ids, include_total=False)
            if not databases:
                queryset = queryset.none()
            else:
                queryset = queryset.filter(
                    resumefile__database_memberships__resume_database_id__in=[database.id for database in databases]
                ).distinct()
        if name:
            queryset = queryset.filter(
                Q(name__icontains=name) | Q(phone__icontains=name) | Q(email__icontains=name)
            )
        if status:
            if status not in CandidateStatus.values:
                raise AppApiException(400, "status is invalid")
            if status == CandidateStatus.DELETED and self.hr_role != "ADMIN":
                queryset = queryset.none()
            else:
                queryset = queryset.filter(status=status)
        else:
            queryset = queryset.exclude(status=CandidateStatus.DELETED)
        if skills:
            # 0030 后 Candidate 仅 name/phone/email：技能搜索改为 纯简历原文/正文 命中（raw_text 优先 + 段落兜底），多词 AND。
            terms = [term.strip() for term in skills.split(",") if term.strip()]
            if terms:
                from knowledge.models import Paragraph
                skills_q = Q()
                resume_doc_ids = list(
                    ResumeFile.objects.filter(workspace_id=self.workspace_id, document_id__isnull=False)
                    .values_list("document_id", flat=True)
                )
                for term in terms:
                    text_doc_ids = list(
                        Paragraph.objects.filter(
                            document_id__in=resume_doc_ids, content__icontains=term, is_active=True
                        ).values_list("document_id", flat=True)
                    )
                    text_candidate_ids = set(
                        ResumeFile.objects.filter(document_id__in=text_doc_ids)
                        .values_list("candidate_id", flat=True)
                    )
                    text_candidate_ids.update(
                        ResumeFile.objects.filter(workspace_id=self.workspace_id, raw_text__icontains=term)
                        .values_list("candidate_id", flat=True)
                    )
                    skills_q &= Q(id__in=text_candidate_ids)
                queryset = queryset.filter(skills_q).distinct()
        owner_id = query.get("owner_id")
        if owner_id:
            owner_id = self._owner_id({"owner_id": owner_id})
            queryset = queryset.filter(
                id__in=Application.objects.filter(
                    workspace_id=self.workspace_id, owner_id=owner_id
                ).values("candidate_id")
            )
        return queryset

    def page_candidates(self, current_page, page_size, query):
        current_page = max(1, int(current_page))  # P3-1: 钳制页码≥1，防 current_page=0 负切片 AssertionError
        queryset = self._filter_candidates(query)
        total = queryset.count()
        start = (current_page - 1) * page_size
        candidates = queryset.order_by("-update_time")[start:start + page_size]
        records = [self._candidate_output(candidate) for candidate in candidates]
        self._attach_duplicate_ids(records, candidates)
        return {"total": total, "records": records}

    def _attach_duplicate_ids(self, records, candidates):
        # 批量预取（P3-2）：phone 精确匹配、email 大小写不敏感各 1 次批量查询，
        # 消除此前 email 逐条 iexact 造成的每行一查 N+1。
        candidates = list(candidates)
        phones = {c.phone for c in candidates if c.phone}
        emails = {c.email for c in candidates if c.email}
        phone_map = {}
        if phones:
            for cand_id, phone in Candidate.objects.filter(workspace_id=self.workspace_id, phone__in=phones).values_list("id", "phone"):
                phone_map.setdefault(phone, set()).add(cand_id)
        email_map = {}
        if emails:
            # 页内全部 email OR 合并为一次 iexact 查询，再按小写 email 分组（与逐条 iexact 同义）
            email_conditions = reduce(or_, (Q(email__iexact=email) for email in emails))
            rows = Candidate.objects.filter(workspace_id=self.workspace_id).filter(email_conditions).values_list("id", "email")
            for cand_id, email in rows:
                email_map.setdefault(email.lower(), set()).add(cand_id)
        for record, candidate in zip(records, candidates):
            dupes = set()
            if candidate.phone and candidate.phone in phone_map:
                dupes.update(phone_map[candidate.phone] - {candidate.id})
            if candidate.email:
                dupes.update(email_map.get(candidate.email.lower(), set()) - {candidate.id})
            record["duplicate_ids"] = [str(item) for item in dupes]

    def get_candidate(self, candidate_id):
        candidate = self._candidate(candidate_id)
        if candidate.status == CandidateStatus.DELETED and self.hr_role != "ADMIN":
            raise NotFound404(404, "Resource not found")
        applications = Application.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
        ).select_related("job", "current_stage").order_by("-update_time")
        result = self._candidate_output(candidate)
        result["applications"] = [
            {
                "id": str(app.id),
                "job_id": str(app.job_id),
                "job_name": app.job.name,
                "status": app.status,
                "current_stage": app.current_stage.key if app.current_stage else "",
                "owner_id": str(app.owner_id) if app.owner_id else None,
            }
            for app in applications
        ]
        write_audit_log(self.workspace_id, self.user_id, "VIEW_DETAIL", "CANDIDATE", candidate.id)
        return result

    def edit_candidate(self, candidate_id, data):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        if candidate.status == CandidateStatus.DELETED:
            raise AppApiException(400, "deleted candidate cannot be edited")
        update_fields = []
        if "name" in data:
            candidate.name = self._required_string(data, "name", 128)
            update_fields.append("name")
        if "phone" in data:
            candidate.phone = self._optional_string(data, "phone", 20)
            update_fields.append("phone")
        if "email" in data:
            email = data.get("email")
            candidate.email = email or None
            if candidate.email and "@" not in candidate.email:
                raise AppApiException(400, "email is invalid")
            update_fields.append("email")
        if not update_fields:
            return self._candidate_output(candidate)
        candidate.save(update_fields=[*update_fields, "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "UPDATE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    def archive_candidate(self, candidate_id):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        if candidate.status == CandidateStatus.DELETED:
            raise AppApiException(400, "deleted candidate cannot be archived")
        if Application.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            status=ApplicationStatus.ACTIVE,
        ).exists():
            raise AppApiException(400, "Candidate has an active assignment")
        candidate.status = CandidateStatus.ARCHIVED
        candidate.save(update_fields=["status", "update_time"])
        for resume in ResumeFile.objects.filter(workspace_id=self.workspace_id, candidate=candidate):
            set_resume_index_active(resume, False)
            log_flow(self.workspace_id, "LIFECYCLE", resume_id=resume.id, document_id=resume.document_id,
                     detail={"action": "archive", "is_active": False})
        write_audit_log(self.workspace_id, self.user_id, "ARCHIVE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    def restore_candidate(self, candidate_id):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        if candidate.status == CandidateStatus.DELETED:
            raise AppApiException(400, "deleted candidate cannot be restored")
        if candidate.status != CandidateStatus.ARCHIVED:
            raise AppApiException(400, "Candidate is not archived")
        candidate.status = CandidateStatus.ACTIVE
        candidate.save(update_fields=["status", "update_time"])
        for resume in ResumeFile.objects.filter(workspace_id=self.workspace_id, candidate=candidate):
            set_resume_index_active(resume, True)
            log_flow(self.workspace_id, "LIFECYCLE", resume_id=resume.id, document_id=resume.document_id,
                     detail={"action": "restore", "is_active": True})
        write_audit_log(self.workspace_id, self.user_id, "RESTORE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    def delete_candidate(self, candidate_id):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        if Application.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            status=ApplicationStatus.ACTIVE,
        ).exists():
            raise AppApiException(400, "Candidate has an active assignment")
        if Application.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            status=ApplicationStatus.HIRED,
        ).exists():
            raise AppApiException(400, "Candidate is hired, cannot delete")
        storage = get_storage()
        for resume in ResumeFile.objects.filter(workspace_id=self.workspace_id, candidate=candidate):
            delete_resume_index(resume)
            log_flow(self.workspace_id, "LIFECYCLE", resume_id=resume.id,
                     detail={"action": "delete", "document_id": str(resume.document_id) if resume.document_id else None})
            delete_flow_logs(self.workspace_id, resume.id)
            file_delete_failed = False
            if resume.file_path and storage.exists(resume.file_path):
                try:
                    storage.delete(resume.file_path)
                except OSError:
                    file_delete_failed = True
            write_audit_log(
                self.workspace_id, resume.user_id or self.user_id, "RESUME_DELETE", "RESUME", resume.id,
                result="FAILED" if file_delete_failed else "SUCCESS",
                detail="resume file removal failed" if file_delete_failed else "",
            )
            resume.delete()
        candidate.name = "已删除候选人"
        candidate.email = None
        candidate.phone = ""
        candidate.status = CandidateStatus.DELETED
        candidate.save(update_fields=["name", "email", "phone", "status", "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "DELETE", "CANDIDATE", candidate.id)
        return self._candidate_output(candidate)

    @staticmethod
    def _candidate_export_row(candidate):
        return {
            "name": candidate.name,
            "status": candidate.status,
            "create_time": candidate.create_time.isoformat(),
        }

    def export_candidates(self, filters):
        self._require_manage()
        records = [
            self._candidate_export_row(candidate)
            for candidate in self._filter_candidates(filters)
        ]
        write_audit_log(
            self.workspace_id, self.user_id, "EXPORT", "CANDIDATE",
            detail=f"exported {len(records)} records by user {self.user_id}",
        )
        return records

    def create_job(self, data):
        self._require_manage()
        headcount = data.get("headcount", 1)
        if isinstance(headcount, bool) or not isinstance(headcount, int) or not 1 <= headcount <= 999:
            raise AppApiException(400, "headcount must be between 1 and 999")
        job = Job.objects.create(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            owner_id=self._owner_id(data) or self.user_id,
            name=self._required_string(data, "name", 128),
            department=self._optional_string(data, "department", 128),
            city=self._optional_string(data, "city", 64),
            level=self._optional_string(data, "level", 64),
            headcount=headcount,
            description=self._optional_string(data, "description", 4096),
            skill_requirements=self._skill_requirements(data),
        )
        create_default_stages(self.workspace_id, job, self.user_id)
        write_audit_log(self.workspace_id, self.user_id, "CREATE", "JOB", job.id)
        return self._job_output(job)

    def page_jobs(self, current_page, page_size, query):
        current_page = max(1, int(current_page))  # P3-1: 钳制页码≥1，防 current_page=0 负切片 AssertionError
        queryset = Job.objects.filter(workspace_id=self.workspace_id)
        name = query.get("name")
        status = query.get("status")
        owner_id = query.get("owner_id")
        if name:
            queryset = queryset.filter(name__icontains=name)
        if status:
            if status not in JobStatus.values:
                raise AppApiException(400, "status is invalid")
            queryset = queryset.filter(status=status)
        if owner_id:
            queryset = queryset.filter(owner_id=self._owner_id({"owner_id": owner_id}))
        queryset = queryset.annotate(
            active_assignment_count=Count(
                "applications",
                filter=Q(applications__status=ApplicationStatus.ACTIVE),
            )
        )
        total = queryset.count()
        start = (current_page - 1) * page_size
        records = queryset.order_by("-update_time")[start:start + page_size]
        return {"total": total, "records": [self._job_output(job) for job in records]}

    def get_job(self, job_id):
        job = self._job(job_id)
        result = self._job_output(job)
        applications = Application.objects.filter(
            workspace_id=self.workspace_id,
            job=job,
        ).select_related("candidate", "current_stage").order_by("-update_time")
        result["applications"] = [
            {
                "id": str(app.id),
                "candidate_id": str(app.candidate_id),
                "candidate_name": app.candidate.name,
                "status": app.status,
                "current_stage": app.current_stage.key if app.current_stage else "",
                "owner_id": str(app.owner_id) if app.owner_id else None,
            }
            for app in applications
        ]
        applications = Application.objects.filter(
            workspace_id=self.workspace_id,
            job=job,
        ).select_related("candidate", "current_stage").order_by("-update_time")
        result["active_assignment_count"] = applications.filter(status=ApplicationStatus.ACTIVE).count()
        application_records = [
            {
                "application_id": str(application.id),
                "candidate_id": str(application.candidate_id),
                "candidate_name": application.candidate.name,
                "current_stage": {
                    "id": str(application.current_stage.id),
                    "key": application.current_stage.key,
                    "name": application.current_stage.name,
                    "order": application.current_stage.order,
                } if application.current_stage else None,
                "status": application.status,
                "relation_type": application.relation_type,
                "channel": application.channel,
                "owner_id": str(application.owner_id) if application.owner_id else None,
                "reapply_no": application.reapply_no,
                "note": application.note,
                "applied_at": application.applied_at,
                "update_time": application.update_time,
            }
            for application in applications
        ]
        # D1：附带最新 Agent 建议摘要（看板徽标与报告卡入口）
        proposal_by_target = {}
        if application_records:
            proposal_rows = HrAgentProposal.objects.filter(
                workspace_id=self.workspace_id,
                target_type="APPLICATION",
                target_id__in=[record["application_id"] for record in application_records],
            ).order_by("-create_time")
            seen = set()
            for proposal in proposal_rows:
                if proposal.target_id in seen:
                    continue
                seen.add(proposal.target_id)
                proposal_by_target[proposal.target_id] = {
                    "proposal_id": str(proposal.id),
                    "action": proposal.action,
                    "status": proposal.status,
                    "score": (proposal.payload_json or {}).get("decision", {}).get("score"),
                    "create_time": proposal.create_time,
                }
        for record in application_records:
            record["agent"] = proposal_by_target.get(record["application_id"])
        result["applications"] = application_records
        # 前端职位展开行候选人列表读取 assignments（与 candidates 详情保持一致）
        result["assignments"] = application_records
        write_audit_log(self.workspace_id, self.user_id, "VIEW_DETAIL", "JOB", job.id)
        return result

    def edit_job(self, job_id, data):
        self._require_manage()
        job = self._job(job_id)
        fields = {
            "name": (self._required_string, 128),
            "department": (self._optional_string, 128),
            "city": (self._optional_string, 64),
            "level": (self._optional_string, 64),
            "description": (self._optional_string, 4096),
        }
        update_fields = []
        for field, (validator, maximum) in fields.items():
            if field in data:
                setattr(job, field, validator(data, field, maximum))
                update_fields.append(field)
        if "headcount" in data:
            headcount = data["headcount"]
            if isinstance(headcount, bool) or not isinstance(headcount, int) or not 1 <= headcount <= 999:
                raise AppApiException(400, "headcount must be between 1 and 999")
            job.headcount = headcount
            update_fields.append("headcount")
        if "skill_requirements" in data:
            job.skill_requirements = self._skill_requirements(data)
            update_fields.append("skill_requirements")
        if "status" in data:
            if data["status"] not in JobStatus.values:
                raise AppApiException(400, "status is invalid")
            if job.status == JobStatus.CLOSED and data["status"] != JobStatus.CLOSED:
                raise AppApiException(400, "closed job must be reopened via reopen endpoint")
            if data["status"] == JobStatus.CLOSED and job.status != JobStatus.CLOSED:
                raise AppApiException(
                    400, "Use POST /hr/jobs/{id}/close to close a job (requires close_reason and active application handling)"
                )
            if data["status"] == JobStatus.CLOSED:
                job.close_reason = self._close_reason(data)
                update_fields.append("close_reason")
            job.status = data["status"]
            update_fields.append("status")
        if "owner_id" in data:
            job.owner_id = self._owner_id(data)
            update_fields.append("owner_id")
        if "close_reason" in data:
            value = data["close_reason"] or None
            if value is not None and value not in JobCloseReason.values:
                raise AppApiException(400, "close_reason is invalid")
            final_status = data.get("status") or job.status
            if value is not None and final_status != JobStatus.CLOSED:
                raise AppApiException(400, "close_reason only valid for CLOSED status")
            job.close_reason = value
            if "close_reason" not in update_fields:
                update_fields.append("close_reason")
        if update_fields:
            job.save(update_fields=[*update_fields, "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "UPDATE", "JOB", job.id)
        return self._job_output(job)
    def reopen_job(self, job_id):
        self._require_manage()
        job = self._job(job_id)
        if job.status not in (JobStatus.ON_HOLD, JobStatus.CLOSED):
            raise AppApiException(400, "Job is not on hold or closed")
        job.status = JobStatus.OPEN
        job.close_reason = None
        job.save(update_fields=["status", "close_reason", "update_time"])
        write_audit_log(self.workspace_id, self.user_id, "JOB_REOPEN", "JOB", job.id)
        return self._job_output(job)
    @staticmethod
    def _resume_key(workspace_id, sha256, extension):
        return os.path.join("resume", workspace_id, f"{sha256}.{extension}")

    @staticmethod
    def _resume_output(resume):
        memberships = list(
            ResumeDatabaseMembership.objects.filter(resume_file=resume).select_related("resume_database")
        )
        return {
            "id": str(resume.id),
            "file_name": resume.file_name,
            "extension": resume.extension,
            "file_size": resume.file_size,
            "sha256": resume.sha256,
            "source_channel": resume.source_channel,
            "resume_database_id": str(resume.resume_database_id),
            "resume_database_name": resume.resume_database.name if resume.resume_database_id else "",
            "resume_database_ids": [str(item.resume_database_id) for item in memberships],
            "resume_database_names": [item.resume_database.name for item in memberships],
            "status": resume.status,
            "error_message": resume.error_message,
            "document_id": str(resume.document_id) if resume.document_id else None,
            "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
            "create_time": resume.create_time,
            "update_time": resume.update_time,
        }

    def upload_resumes(self, files, source_channel, resume_database_ids=None):
        self._require_operator()
        databases = self._resume_databases(resume_database_ids, include_total=True)
        resume_database = databases[0]
        database_ids = [str(database.id) for database in databases]
        database_names = [database.name for database in databases]
        if source_channel not in ResumeChannel.values:
            raise AppApiException(400, "source_channel is invalid")
        records = []
        for file_path, file_name, extension in files:
            extension = extension.lower()
            if extension not in ("docx", "txt"):
                raise AppApiException(400, f"File format {extension} is not supported")
            size = os.path.getsize(file_path)
            if size > 20 * 1024 * 1024:
                raise AppApiException(400, "File exceeds 20 MB limit")
            digest = hashlib.sha256()
            with open(file_path, "rb") as handle:
                digest.update(handle.read())
            sha256 = digest.hexdigest()
            existing = ResumeFile.objects.filter(workspace_id=self.workspace_id, sha256=sha256).first()
            if existing:
                self._attach_resume_databases(existing, databases)
                os.remove(file_path)
                log_flow(self.workspace_id, "UPLOAD", resume_id=existing.id,
                         detail={"file_name": file_name, "file_size": size, "sha256": sha256,
                                  "extension": extension, "duplicate": True})
                records.append({
                    "resume_id": str(existing.id),
                    "file_name": existing.file_name,
                    "status": existing.status,
                    "resume_database_id": str(existing.resume_database_id),
                    "resume_database_name": "、".join(database_names),
                    "resume_database_ids": database_ids,
                    "resume_database_names": database_names,
                    "sha256": existing.sha256,
                    "duplicate": True,
                    "candidate_id": str(existing.candidate_id) if existing.candidate_id else None,
                    "document_id": str(existing.document_id) if existing.document_id else None,
                    "error_message": existing.error_message,
                })
                continue
            stored = get_storage().save(
                self._resume_key(self.workspace_id, sha256, extension), file_path
            )
            os.remove(file_path)
            resume = ResumeFile.objects.create(
                workspace_id=self.workspace_id, file_name=file_name, extension=extension,
                file_path=stored, file_size=size, sha256=sha256,
                source_channel=source_channel, resume_database=resume_database,
                status=ResumeStatus.PENDING, user_id=self.user_id,
            )
            self._attach_resume_databases(resume, databases)
            log_flow(self.workspace_id, "UPLOAD", resume_id=resume.id,
                     detail={"file_name": file_name, "file_size": size, "sha256": sha256,
                             "extension": extension, "duplicate": False})
            try:
                parse_resume_task.delay(str(resume.id))
                status = ResumeStatus.PENDING
                error_message = ""
            except AlreadyQueued as exc:
                raise AppApiException(500, "任务已存在，请稍后查询") from exc
            except Exception as exc:
                resume.status = ResumeStatus.FAILED
                resume.error_message = str(exc)
                resume.save(update_fields=["status", "error_message", "update_time"])
                status = ResumeStatus.FAILED
                error_message = str(exc)
            records.append({
                "resume_id": str(resume.id),
                "file_name": resume.file_name,
                "status": status,
                "resume_database_id": str(resume.resume_database_id),
                "resume_database_name": "、".join(database_names),
                "resume_database_ids": database_ids,
                "resume_database_names": database_names,
                "sha256": resume.sha256,
                "duplicate": False,
                "candidate_id": None,
                "document_id": str(resume.document_id) if resume.document_id else None,
                "error_message": error_message,
            })
        write_audit_log(
            self.workspace_id, self.user_id, "RESUME_UPLOAD", "RESUME",
            object_id=",".join(str(record["resume_id"]) for record in records),
        )
        return records

    def list_candidate_resumes(self, candidate_id):
        candidate = self._candidate(candidate_id)
        resumes = ResumeFile.objects.filter(workspace_id=self.workspace_id, candidate=candidate).order_by("-create_time")
        return [self._resume_output(resume) for resume in resumes]

    def delete_resume(self, resume_id):
        self._require_manage()
        resume = ResumeFile.objects.filter(id=resume_id, workspace_id=self.workspace_id).first()
        if resume is None:
            raise NotFound404(404, "Resource not found")
        # 语义索引联动清理（幂等）+ 流转日志清理（EXTRACT/SANITIZE 含未脱敏全文，删除后不留存）
        delete_resume_index(resume)
        log_flow(self.workspace_id, "LIFECYCLE", resume_id=resume.id,
                 detail={"action": "delete", "document_id": str(resume.document_id) if resume.document_id else None})
        delete_flow_logs(self.workspace_id, resume.id)
        if resume.file_path:
            try:
                get_storage().delete(resume.file_path)
            except OSError:
                pass
        resume.delete()
        write_audit_log(self.workspace_id, self.user_id, "RESUME_DELETE", "RESUME", resume_id)
        return True

    def _resume_file(self, resume_id):
        resume = ResumeFile.objects.filter(id=resume_id, workspace_id=self.workspace_id).first()
        if resume is None:
            raise NotFound404(404, "Resource not found")
        return resume

    def download_resume(self, resume_id):
        self._require_operator()
        resume = self._resume_file(resume_id)
        if not resume.file_path or not get_storage().exists(resume.file_path):
            raise NotFound404(404, "File not found")
        content_type = {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
        }.get(resume.extension.lower(), "application/octet-stream")
        write_audit_log(self.workspace_id, self.user_id, "RESUME_DOWNLOAD", "RESUME", resume_id)
        return get_storage().open(resume.file_path), resume.file_name, content_type

    def resume_content(self, resume_id):
        self._require_operator()
        resume = self._resume_file(resume_id)
        if not resume.file_path or not get_storage().exists(resume.file_path):
            raise NotFound404(404, "File not found")
        local_path = get_storage().open(resume.file_path)
        # S3 后端 open 会物化到临时文件，需在使用后清理（P2-26）
        is_temp = local_path.startswith(tempfile.gettempdir()) if local_path else False
        try:
            if resume.extension.lower() == "docx":
                text = extract_text_from_docx(local_path)
            else:
                text = extract_text_from_txt(local_path)
        except Exception as exc:
            raise AppApiException(400, "简历内容提取失败") from exc
        finally:
            if is_temp:
                try:
                    if os.path.exists(local_path):
                        os.remove(local_path)
                except Exception:
                    pass
        return {"content": text}

    def check_duplicate(self, data):
        phone = data.get("phone")
        email = data.get("email")
        exclude_id = data.get("exclude_id")
        if (not isinstance(phone, str) or not phone.strip()) and (not isinstance(email, str) or not email.strip()):
            return {"candidates": []}
        queryset = Candidate.objects.filter(workspace_id=self.workspace_id)
        if exclude_id:
            try:
                uuid.UUID(exclude_id)
            except (ValueError, TypeError) as exc:
                raise AppApiException(400, "exclude_id is invalid") from exc
            queryset = queryset.exclude(id=exclude_id)
        matches = []
        seen = set()
        if isinstance(phone, str) and phone.strip():
            for row in queryset.filter(phone=phone.strip()):
                if row.id not in seen:
                    seen.add(row.id)
                    matches.append(row)
        if isinstance(email, str) and email.strip():
            for row in queryset.filter(email__iexact=email.strip()):
                if row.id not in seen:
                    seen.add(row.id)
                    matches.append(row)
        return {
            "candidates": [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "phone": self._masked_phone(row.phone) if self.hr_role == "VIEWER" else row.phone,
                    "email": self._masked_email(row.email) if self.hr_role == "VIEWER" else row.email,
                }
                for row in matches[:20]
            ]
        }

    def merge_candidates(self, primary_id, data):
        self._require_manage()
        secondary_id = data.get("secondary_id")
        if not isinstance(secondary_id, str) or not secondary_id.strip():
            raise AppApiException(400, "secondary_id is required")
        primary = self._candidate(primary_id)
        secondary = self._candidate(secondary_id)
        if primary.id == secondary.id:
            raise AppApiException(400, "不能与自己合并")
        if primary.status == CandidateStatus.DELETED or secondary.status == CandidateStatus.DELETED:
            raise AppApiException(400, "deleted candidate cannot be merged")
        with transaction.atomic():
            primary = Candidate.objects.select_for_update().get(id=primary.id)
            secondary = Candidate.objects.select_for_update().get(id=secondary.id)
            primary_jobs = set(
                Application.objects.filter(candidate=primary, status=ApplicationStatus.ACTIVE)
                .values_list("job_id", flat=True)
            )
            if Application.objects.filter(
                candidate=secondary, status=ApplicationStatus.ACTIVE, job_id__in=primary_jobs
            ).exists():
                raise AppApiException(400, "存在与主候选人冲突的有效指派，请先调整")
            if not primary.name:
                primary.name = secondary.name
            if not primary.email:
                primary.email = secondary.email
            if not primary.phone:
                primary.phone = secondary.phone
            primary.save(update_fields=["name", "email", "phone", "update_time"])
            ResumeFile.objects.filter(candidate=secondary).update(candidate=primary)
            Application.objects.filter(candidate=secondary).update(candidate=primary)
            # 审查修复 #2：先迁移 Offer/OnboardingHandoff 归属再删 secondary，防止 CASCADE 静默销毁
            Offer.objects.filter(candidate=secondary).update(candidate=primary)
            OnboardingHandoff.objects.filter(candidate=secondary).update(candidate=primary)
            secondary.delete()
        write_audit_log(self.workspace_id, self.user_id, "MERGE", "CANDIDATE", primary.id, detail=str(secondary_id))
        return self.get_candidate(primary_id)

    def batch_resume_status(self, resume_ids):
        try:
            cleaned_ids = [uuid.UUID(item) for item in resume_ids]
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "ids is invalid") from exc
        resumes = ResumeFile.objects.filter(workspace_id=self.workspace_id, id__in=cleaned_ids)
        return [
            {
                "resume_id": str(resume.id),
                "file_name": resume.file_name,
                "status": resume.status,
                "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
                "document_id": str(resume.document_id) if resume.document_id else None,
                "error_message": resume.error_message,
            }
            for resume in resumes
        ]

    def match_job_candidates(self, job_id, current_page, page_size):
        current_page = max(1, int(current_page))  # P3-1: 钳制页码≥1，防 current_page=0 负下标错位
        job = self._job(job_id)
        if job.status != JobStatus.OPEN:
            raise AppApiException(400, "Job is closed")
        requirements = job.skill_requirements
        requirement_lower = [skill.lower() for skill in requirements]
        candidates = Candidate.objects.filter(workspace_id=self.workspace_id, status=CandidateStatus.ACTIVE)
        # 0030 后 Candidate 仅 name/phone/email：匹配仅依赖 简历正文关键词召回（paragraph ILike）与语义补充，不再读 candidate.skills/城市。
        keyword_hit_ids = self._keyword_match_candidate_ids(requirements)
        records = []
        scored_ids = set()
        for candidate in candidates:
            score = 0
            matched = []
            candidate_id_str = str(candidate.id)
            for index, skill in enumerate(requirement_lower):
                if candidate_id_str in keyword_hit_ids.get(skill, ()):
                    score += 2
                    matched.append(requirements[index])
            if score > 0:
                records.append({
                    "candidate_id": str(candidate.id),
                    "name": candidate.name,
                    "match_score": score,
                    "matched_skills": matched,
                    "create_time": candidate.create_time,
                })
                scored_ids.add(str(candidate.id))
        # 语义补充：skills 字段常缺失/为长句，结构化匹配会漏掉简历正文相关的候选人。
        # 用 dense 模式检索简历知识库（显式 dense 跳过结构化技能预筛，避免脏技能表误杀），
        # 命中简历正文的候选人并入匹配结果；知识库/模型缺失时优雅跳过，不影响结构化结果。
        semantic_records = self._semantic_match_candidates(job, requirements, scored_ids)
        # 语义命中补充 create_time（同分时按导入时间排序，近期导入优先展示）
        if semantic_records:
            time_map = dict(
                Candidate.objects.filter(
                    id__in=[record["candidate_id"] for record in semantic_records]
                ).values_list("id", "create_time")
            )
            for record in semantic_records:
                record["create_time"] = time_map.get(uuid.UUID(record["candidate_id"]))
        records.extend(semantic_records)
        from datetime import datetime as _datetime

        records.sort(
            key=lambda item: (item["match_score"], item.get("create_time") or _datetime.min),
            reverse=True,
        )
        total = len(records)
        start = (current_page - 1) * page_size
        return {"total": total, "records": records[start:start + page_size]}

    def _keyword_match_candidate_ids(self, requirements):
        """按需求技能在简历原文（raw_text + paragraph）中做 ILike 关键词召回，返回 {skill_lower: set(candidate_id_str)}。"""
        from knowledge.models import Paragraph

        result = {}
        for skill in requirements:
            term = (skill or "").strip()
            if not term:
                continue
            candidate_ids: set[str] = set()
            # raw_text 优先：覆盖未建 paragraph / document_id 缺口的简历
            raw_ids = ResumeFile.objects.filter(
                workspace_id=self.workspace_id, raw_text__icontains=term
            ).values_list("candidate_id", flat=True)
            for cid in raw_ids:
                if cid:
                    candidate_ids.add(str(cid))
            # paragraph 兜底：覆盖 raw_text 为空的存量简历
            doc_ids = list(
                Paragraph.objects.filter(content__icontains=term).values_list("document_id", flat=True)
            )
            if doc_ids:
                para_ids = ResumeFile.objects.filter(
                    workspace_id=self.workspace_id, document_id__in=doc_ids
                ).values_list("candidate_id", flat=True)
                for cid in para_ids:
                    if cid:
                        candidate_ids.add(str(cid))
            if candidate_ids:
                result[term.lower()] = candidate_ids
        return result

    def _semantic_match_candidates(self, job, requirements, exclude_ids):
        query_parts = [skill for skill in requirements if skill and skill.strip()]
        if job.description:
            query_parts.append(job.description)
        query = " ".join(query_parts).strip()[:200]
        if not query:
            return []
        try:
            from hr.services.resume_search import search_resumes

            result = search_resumes(
                self.workspace_id, query, top_k=20, mode="dense",
                hr_role=self.hr_role, user_id=self.user_id,
            )
        except Exception:
            return []
        items = result.get("items", []) if isinstance(result, dict) else []
        added = []
        seen = set()
        for item in items:
            candidate = item.get("candidate")
            if not isinstance(candidate, dict):
                continue
            cid = str(candidate.get("id") or "")
            if not cid or cid in exclude_ids or cid in seen:
                continue
            seen.add(cid)
            score_map = item.get("score") or {}
            raw = score_map.get("rerank") or score_map.get("dense") or score_map.get("resume") or 0
            # 语义得分映射为与结构化分同量纲的整数（2 分=一项技能精确命中）
            mapped = min(2, max(1, round(float(raw) * 6))) if raw else 1
            added.append({
                "candidate_id": cid,
                "name": candidate.get("name") or "",
                "match_score": mapped,
                "matched_skills": [skill for skill in requirements if skill and skill.strip()],
            })
        return added

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
