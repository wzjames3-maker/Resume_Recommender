import hashlib
import os
import shutil
from datetime import datetime

import uuid_utils.compat as uuid
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from celery_once import AlreadyQueued
from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    ACTIVE_ASSIGNMENT_STATUSES,
    AssignmentStatus,
    Candidate,
    CandidateAssignment,
    CandidateStatus,
    Interview,
    InterviewStatus,
    Job,
    JobCloseReason,
    JobStatus,
    RelationType,
    ResumeChannel,
    ResumeFile,
    ResumeStatus,
    TerminationReason,
)
from hr.services.resume_parser import extract_text_from_docx, extract_text_from_txt
from hr.task.resume import parse_resume_task
from maxkb.const import PROJECT_DIR

TERMINATION_REASON_REQUIRED_STATUSES = [
    AssignmentStatus.REJECTED,
    AssignmentStatus.WITHDRAWN,
    AssignmentStatus.CLOSED,
]

JOB_OPEN_REQUIRED_TARGETS = [
    AssignmentStatus.INTERVIEWING,
    AssignmentStatus.OFFER,
    AssignmentStatus.HIRED,
]

_ALLOWED_TRANSITIONS = {
    AssignmentStatus.PENDING_SCREEN: {
        AssignmentStatus.SCREEN_PASSED,
        AssignmentStatus.REJECTED,
        AssignmentStatus.WITHDRAWN,
        AssignmentStatus.CLOSED,
    },
    AssignmentStatus.SCREEN_PASSED: {
        AssignmentStatus.INTERVIEWING,
        AssignmentStatus.REJECTED,
        AssignmentStatus.WITHDRAWN,
        AssignmentStatus.CLOSED,
    },
    AssignmentStatus.INTERVIEWING: {
        AssignmentStatus.OFFER,
        AssignmentStatus.REJECTED,
        AssignmentStatus.WITHDRAWN,
        AssignmentStatus.CLOSED,
    },
    AssignmentStatus.OFFER: {
        AssignmentStatus.HIRED,
        AssignmentStatus.REJECTED,
        AssignmentStatus.WITHDRAWN,
        AssignmentStatus.CLOSED,
    },
    AssignmentStatus.REJECTED: {
        AssignmentStatus.PENDING_SCREEN,
    },
}


class RecruitmentService:
    def __init__(self, workspace_id, user_id, is_workspace_manage):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.is_workspace_manage = is_workspace_manage

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

    def _assignment(self, assignment_id):
        assignment = CandidateAssignment.objects.filter(id=assignment_id, workspace_id=self.workspace_id).first()
        if assignment is None:
            raise NotFound404(404, "Resource not found")
        return assignment

    def _require_manage(self):
        if not self.is_workspace_manage:
            raise AppUnauthorizedFailed(403, "Workspace administrator permission is required")

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
    def _skills(data):
        skills = data.get("skills", [])
        if not isinstance(skills, list) or any(not isinstance(skill, str) or not skill.strip() for skill in skills):
            raise AppApiException(400, "skills must be a list of non-empty strings")
        return [skill.strip() for skill in skills]

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

    @staticmethod
    def _candidate_output(candidate):
        return {
            "id": str(candidate.id),
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "current_city": candidate.current_city,
            "target_city": candidate.target_city,
            "highest_degree": candidate.highest_degree,
            "years_experience": candidate.years_experience,
            "skills": candidate.skills,
            "source": candidate.source,
            "note": candidate.note,
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

    @staticmethod
    def _assignment_output(assignment):
        return {
            "id": str(assignment.id),
            "candidate_id": str(assignment.candidate_id),
            "job_id": str(assignment.job_id),
            "status": assignment.status,
            "relation_type": assignment.relation_type,
            "channel": assignment.channel,
            "applied_at": assignment.applied_at,
            "owner_id": str(assignment.owner_id) if assignment.owner_id else None,
            "termination_reason": assignment.termination_reason,
            "is_reapply": assignment.is_reapply,
            "note": assignment.note,
            "create_time": assignment.create_time,
            "update_time": assignment.update_time,
        }

    def create_candidate(self, data):
        candidate = Candidate.objects.create(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            name=self._required_string(data, "name", 128),
            email=data.get("email") or None,
            phone=self._optional_string(data, "phone", 20),
            current_city=self._optional_string(data, "current_city", 64),
            target_city=self._optional_string(data, "target_city", 64),
            highest_degree=self._optional_string(data, "highest_degree", 32),
            years_experience=self._years_experience(data),
            skills=self._skills(data),
            source=self._optional_string(data, "source", 64),
            note=self._optional_string(data, "note", 4096),
        )
        return self._candidate_output(candidate)

    @staticmethod
    def _years_experience(data):
        value = data.get("years_experience")
        if value in (None, ""):
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 99:
            raise AppApiException(400, "years_experience is invalid")
        return value

    def page_candidates(self, current_page, page_size, query):
        queryset = Candidate.objects.filter(workspace_id=self.workspace_id)
        name = query.get("name")
        city = query.get("city")
        status = query.get("status")
        skills = query.get("skills")
        years_min = query.get("years_min")
        years_max = query.get("years_max")
        source = query.get("source")
        highest_degree = query.get("highest_degree")
        if name:
            queryset = queryset.filter(name__icontains=name)
        if city:
            queryset = queryset.filter(Q(current_city__icontains=city) | Q(target_city__icontains=city))
        if status:
            if status not in CandidateStatus.values:
                raise AppApiException(400, "status is invalid")
            queryset = queryset.filter(status=status)
        if skills:
            for skill in skills.split(","):
                skill = skill.strip()
                if skill:
                    queryset = queryset.filter(skills__contains=[skill])
        if highest_degree:
            queryset = queryset.filter(highest_degree=highest_degree)
        if years_min:
            try:
                years_min = int(years_min)
            except (TypeError, ValueError) as exc:
                raise AppApiException(400, "years_min is invalid") from exc
            queryset = queryset.filter(years_experience__gte=years_min)
        if years_max:
            try:
                years_max = int(years_max)
            except (TypeError, ValueError) as exc:
                raise AppApiException(400, "years_max is invalid") from exc
            queryset = queryset.filter(years_experience__lte=years_max)
        if source:
            queryset = queryset.filter(source=source)
        owner_id = query.get("owner_id")
        if owner_id:
            queryset = queryset.filter(
                id__in=CandidateAssignment.objects.filter(
                    workspace_id=self.workspace_id, owner_id=owner_id
                ).values("candidate_id")
            )
        total = queryset.count()
        start = (current_page - 1) * page_size
        candidates = queryset.order_by("-update_time")[start:start + page_size]
        records = [self._candidate_output(candidate) for candidate in candidates]
        self._attach_duplicate_ids(records, candidates)
        return {"total": total, "records": records}

    def _attach_duplicate_ids(self, records, candidates):
        for record, candidate in zip(records, candidates):
            dupes = set()
            if candidate.phone:
                dupes.update(
                    Candidate.objects.filter(workspace_id=self.workspace_id, phone=candidate.phone)
                    .exclude(id=candidate.id).values_list("id", flat=True)
                )
            if candidate.email:
                dupes.update(
                    Candidate.objects.filter(workspace_id=self.workspace_id, email__iexact=candidate.email)
                    .exclude(id=candidate.id).values_list("id", flat=True)
                )
            record["duplicate_ids"] = [str(item) for item in dupes]

    def get_candidate(self, candidate_id):
        candidate = self._candidate(candidate_id)
        assignments = CandidateAssignment.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
        ).select_related("job").order_by("-update_time")
        result = self._candidate_output(candidate)
        result["assignments"] = [
            {**self._assignment_output(assignment), "job_name": assignment.job.name}
            for assignment in assignments
        ]
        return result

    def edit_candidate(self, candidate_id, data):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        fields = {
            "name": (self._required_string, 128),
            "phone": (self._optional_string, 20),
            "current_city": (self._optional_string, 64),
            "target_city": (self._optional_string, 64),
            "highest_degree": (self._optional_string, 32),
            "source": (self._optional_string, 64),
            "note": (self._optional_string, 4096),
        }
        update_fields = []
        for field, (validator, maximum) in fields.items():
            if field in data:
                setattr(candidate, field, validator(data, field, maximum))
                update_fields.append(field)
        if "email" in data:
            candidate.email = data["email"] or None
            update_fields.append("email")
        if "years_experience" in data:
            candidate.years_experience = self._years_experience(data)
            update_fields.append("years_experience")
        if "skills" in data:
            candidate.skills = self._skills(data)
            update_fields.append("skills")
        if update_fields:
            candidate.save(update_fields=[*update_fields, "update_time"])
        return self._candidate_output(candidate)

    def archive_candidate(self, candidate_id):
        self._require_manage()
        candidate = self._candidate(candidate_id)
        if CandidateAssignment.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            status__in=ACTIVE_ASSIGNMENT_STATUSES,
        ).exists():
            raise AppApiException(400, "Candidate has an active assignment")
        candidate.status = CandidateStatus.ARCHIVED
        candidate.save(update_fields=["status", "update_time"])
        return self._candidate_output(candidate)

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
        return self._job_output(job)

    def page_jobs(self, current_page, page_size, query):
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
            queryset = queryset.filter(owner_id=owner_id)
        queryset = queryset.annotate(
            active_assignment_count=Count(
                "candidateassignment",
                filter=Q(candidateassignment__status__in=ACTIVE_ASSIGNMENT_STATUSES),
            )
        )
        total = queryset.count()
        start = (current_page - 1) * page_size
        records = queryset.order_by("-update_time")[start:start + page_size]
        return {"total": total, "records": [self._job_output(job) for job in records]}

    def get_job(self, job_id):
        job = self._job(job_id)
        result = self._job_output(job)
        assignments = CandidateAssignment.objects.filter(
            workspace_id=self.workspace_id,
            job=job,
        ).select_related("candidate").order_by("-update_time")
        result["assignments"] = [
            {**self._assignment_output(assignment), "candidate_name": assignment.candidate.name}
            for assignment in assignments
        ]
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
            job.status = data["status"]
            update_fields.append("status")
        if "owner_id" in data:
            job.owner_id = self._owner_id(data)
            update_fields.append("owner_id")
        if "close_reason" in data:
            value = data["close_reason"] or None
            if value is not None and value not in JobCloseReason.values:
                raise AppApiException(400, "close_reason is invalid")
            job.close_reason = value
            update_fields.append("close_reason")
        if update_fields:
            job.save(update_fields=[*update_fields, "update_time"])
        return self._job_output(job)

    def create_assignment(self, job_id, candidate_id, data):
        job = self._job(job_id)
        candidate = self._candidate(candidate_id)
        if job.status != JobStatus.OPEN:
            raise AppApiException(400, "Job is closed")
        if candidate.status != CandidateStatus.ACTIVE:
            raise AppApiException(400, "Candidate is archived")
        if CandidateAssignment.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            status=AssignmentStatus.HIRED,
        ).exists():
            raise AppApiException(400, "Candidate is already hired")
        is_reapply = CandidateAssignment.objects.filter(
            workspace_id=self.workspace_id,
            candidate=candidate,
            job=job,
            status__in=TERMINATION_REASON_REQUIRED_STATUSES,
        ).exists()
        try:
            with transaction.atomic():
                assignment = CandidateAssignment.objects.create(
                    workspace_id=self.workspace_id,
                    user_id=self.user_id,
                    owner_id=self._owner_id(data) or self.user_id,
                    candidate=candidate,
                    job=job,
                    relation_type=self._relation_type(data),
                    channel=self._channel(data),
                    note=self._optional_string(data, "note", 4096),
                    is_reapply=is_reapply,
                )
                applied_at = self._applied_at(data)
                if applied_at is not None:
                    assignment.applied_at = applied_at
                    assignment.save(update_fields=["applied_at"])
        except IntegrityError as exc:
            raise AppApiException(400, "An active assignment already exists") from exc
        return self._assignment_output(assignment)

    def close_job(self, job_id, close_reason):
        self._require_manage()
        job = self._job(job_id)
        reason = self._close_reason({"close_reason": close_reason})
        with transaction.atomic():
            job = Job.objects.select_for_update().get(id=job.id)
            job.status = JobStatus.CLOSED
            job.close_reason = reason
            job.save(update_fields=["status", "close_reason", "update_time"])
            closed_count = CandidateAssignment.objects.filter(
                workspace_id=self.workspace_id,
                job=job,
                status__in=ACTIVE_ASSIGNMENT_STATUSES,
            ).update(
                status=AssignmentStatus.CLOSED,
                termination_reason=TerminationReason.JOB_CLOSED,
                update_time=timezone.now(),
            )
        return {"closed_count": closed_count}

    def reopen_job(self, job_id):
        self._require_manage()
        job = self._job(job_id)
        if job.status not in (JobStatus.ON_HOLD, JobStatus.CLOSED):
            raise AppApiException(400, "Job is not on hold or closed")
        job.status = JobStatus.OPEN
        job.close_reason = None
        job.save(update_fields=["status", "close_reason", "update_time"])
        return self._job_output(job)

    def update_assignment(self, assignment_id, data):
        try:
            with transaction.atomic():
                assignment = CandidateAssignment.objects.select_for_update().filter(
                    id=assignment_id,
                    workspace_id=self.workspace_id,
                ).first()
                if assignment is None:
                    raise NotFound404(404, "Resource not found")
                update_fields = []
                if "status" in data:
                    if data["status"] not in AssignmentStatus.values:
                        raise AppApiException(400, "status is invalid")
                    target_status = data["status"]
                    current_status = assignment.status
                    allowed = _ALLOWED_TRANSITIONS.get(current_status)
                    if allowed is None or target_status not in allowed:
                        raise AppApiException(400, f"Illegal status transition from {current_status} to {target_status}")
                    if current_status == AssignmentStatus.REJECTED and target_status == AssignmentStatus.PENDING_SCREEN:
                        self._require_manage()
                        reason = data.get("note")
                        if not isinstance(reason, str) or not reason.strip():
                            raise AppApiException(400, "restore reason is required")
                        if CandidateAssignment.objects.filter(
                            workspace_id=self.workspace_id,
                            candidate=assignment.candidate,
                            job=assignment.job,
                            status__in=ACTIVE_ASSIGNMENT_STATUSES,
                        ).exclude(id=assignment.id).exists():
                            raise AppApiException(400, "An active assignment already exists")
                        assignment.status = target_status
                        assignment.termination_reason = None
                        assignment.note = f"[restore] {reason.strip()}"
                        update_fields.extend(["status", "termination_reason", "note"])
                    else:
                        if target_status in JOB_OPEN_REQUIRED_TARGETS:
                            job = Job.objects.select_for_update().get(id=assignment.job_id)
                            if job.status != JobStatus.OPEN:
                                raise AppApiException(400, "Job is closed")
                        if target_status in ACTIVE_ASSIGNMENT_STATUSES:
                            candidate = Candidate.objects.select_for_update().get(id=assignment.candidate_id)
                            if candidate.status != CandidateStatus.ACTIVE:
                                raise AppApiException(400, "Candidate is archived")
                        if target_status in TERMINATION_REASON_REQUIRED_STATUSES:
                            assignment.termination_reason = self._termination_reason(data)
                            update_fields.append("termination_reason")
                        assignment.status = target_status
                        update_fields.append("status")
                if "owner_id" in data:
                    assignment.owner_id = self._owner_id(data)
                    update_fields.append("owner_id")
                if "note" in data and "status" not in data:
                    assignment.note = self._optional_string(data, "note", 4096)
                    update_fields.append("note")
                if not update_fields:
                    raise AppApiException(400, "No editable fields supplied")
                assignment.save(update_fields=[*update_fields, "update_time"])
        except IntegrityError as exc:
            raise AppApiException(400, "An active assignment already exists") from exc
        return self._assignment_output(assignment)

    def _resume_dir(self):
        directory = os.path.join(PROJECT_DIR, "data", "resume", self.workspace_id)
        os.makedirs(directory, exist_ok=True)
        return directory

    @staticmethod
    def _resume_output(resume):
        return {
            "id": str(resume.id),
            "file_name": resume.file_name,
            "extension": resume.extension,
            "file_size": resume.file_size,
            "sha256": resume.sha256,
            "source_channel": resume.source_channel,
            "status": resume.status,
            "error_message": resume.error_message,
            "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
            "create_time": resume.create_time,
            "update_time": resume.update_time,
        }

    def upload_resumes(self, files, source_channel):
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
                records.append({
                    "resume_id": str(existing.id),
                    "file_name": existing.file_name,
                    "status": existing.status,
                    "sha256": existing.sha256,
                    "duplicate": True,
                    "candidate_id": str(existing.candidate_id) if existing.candidate_id else None,
                    "error_message": existing.error_message,
                })
                continue
            stored = os.path.join(self._resume_dir(), f"{sha256}.{extension}")
            shutil.move(file_path, stored)
            resume = ResumeFile.objects.create(
                workspace_id=self.workspace_id, file_name=file_name, extension=extension,
                file_path=stored, file_size=size, sha256=sha256,
                source_channel=source_channel, status=ResumeStatus.PENDING, user_id=self.user_id,
            )
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
                "sha256": resume.sha256,
                "duplicate": False,
                "candidate_id": None,
                "error_message": error_message,
            })
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
        resume.delete()
        return True

    def _resume_file(self, resume_id):
        resume = ResumeFile.objects.filter(id=resume_id, workspace_id=self.workspace_id).first()
        if resume is None:
            raise NotFound404(404, "Resource not found")
        return resume

    def download_resume(self, resume_id):
        resume = self._resume_file(resume_id)
        if not os.path.exists(resume.file_path):
            raise NotFound404(404, "File not found")
        content_type = {
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
        }.get(resume.extension.lower(), "application/octet-stream")
        return resume.file_path, resume.file_name, content_type

    def resume_content(self, resume_id):
        resume = self._resume_file(resume_id)
        if not os.path.exists(resume.file_path):
            raise NotFound404(404, "File not found")
        try:
            if resume.extension.lower() == "docx":
                text = extract_text_from_docx(resume.file_path)
            else:
                text = extract_text_from_txt(resume.file_path)
        except Exception as exc:
            raise AppApiException(400, "简历内容提取失败") from exc
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
                {"id": str(row.id), "name": row.name, "phone": row.phone, "email": row.email, "current_city": row.current_city}
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
        with transaction.atomic():
            primary = Candidate.objects.select_for_update().get(id=primary.id)
            secondary = Candidate.objects.select_for_update().get(id=secondary.id)
            primary_jobs = set(
                CandidateAssignment.objects.filter(candidate=primary, status__in=ACTIVE_ASSIGNMENT_STATUSES)
                .values_list("job_id", flat=True)
            )
            if CandidateAssignment.objects.filter(
                candidate=secondary, status__in=ACTIVE_ASSIGNMENT_STATUSES, job_id__in=primary_jobs
            ).exists():
                raise AppApiException(400, "存在与主候选人冲突的有效指派，请先调整")
            if not primary.name:
                primary.name = secondary.name
            if not primary.email:
                primary.email = secondary.email
            if not primary.phone:
                primary.phone = secondary.phone
            if not primary.current_city:
                primary.current_city = secondary.current_city
            if not primary.target_city:
                primary.target_city = secondary.target_city
            if not primary.highest_degree:
                primary.highest_degree = secondary.highest_degree
            if primary.years_experience is None:
                primary.years_experience = secondary.years_experience
            if not primary.source:
                primary.source = secondary.source
            primary.skills = primary.skills + [skill for skill in secondary.skills if skill not in primary.skills]
            primary.note = "\n".join(part for part in [primary.note, secondary.note] if part)
            primary.save()
            ResumeFile.objects.filter(candidate=secondary).update(candidate=primary)
            CandidateAssignment.objects.filter(candidate=secondary).update(candidate=primary)
            secondary.delete()
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
                "error_message": resume.error_message,
            }
            for resume in resumes
        ]

    def match_job_candidates(self, job_id, current_page, page_size):
        job = self._job(job_id)
        if job.status != JobStatus.OPEN:
            raise AppApiException(400, "Job is closed")
        requirements = job.skill_requirements
        requirement_lower = [skill.lower() for skill in requirements]
        candidates = Candidate.objects.filter(workspace_id=self.workspace_id, status=CandidateStatus.ACTIVE)
        records = []
        for candidate in candidates:
            score = 0
            matched = []
            candidate_skills_lower = [skill.lower() for skill in candidate.skills]
            for index, skill in enumerate(requirement_lower):
                if skill in candidate_skills_lower:
                    score += 2
                    matched.append(requirements[index])
            if job.city:
                if candidate.current_city == job.city or candidate.target_city == job.city:
                    score += 2
            if score > 0:
                records.append({
                    "candidate_id": str(candidate.id),
                    "name": candidate.name,
                    "current_city": candidate.current_city,
                    "target_city": candidate.target_city,
                    "years_experience": candidate.years_experience,
                    "skills": candidate.skills,
                    "match_score": score,
                    "matched_skills": matched,
                })
        records.sort(key=lambda item: item["match_score"], reverse=True)
        total = len(records)
        start = (current_page - 1) * page_size
        return {"total": total, "records": records[start:start + page_size]}

    @staticmethod
    def _interview_output(interview):
        return {
            "id": str(interview.id),
            "assignment_id": str(interview.assignment_id),
            "round_no": interview.round_no,
            "interviewer": interview.interviewer,
            "scheduled_at": interview.scheduled_at,
            "status": interview.status,
            "feedback": interview.feedback,
            "create_time": interview.create_time,
            "update_time": interview.update_time,
        }

    def create_interview(self, assignment_id, data):
        assignment = self._assignment(assignment_id)
        max_round = Interview.objects.filter(
            workspace_id=self.workspace_id,
            assignment=assignment,
        ).aggregate(max_round=Max("round_no"))["max_round"] or 0
        interview = Interview.objects.create(
            workspace_id=self.workspace_id,
            assignment=assignment,
            round_no=int(data.get("round_no", max_round + 1)),
            interviewer=self._optional_string(data, "interviewer", 64),
            scheduled_at=data.get("scheduled_at") or None,
            user_id=self.user_id,
        )
        return self._interview_output(interview)

    def list_interviews(self, assignment_id):
        assignment = self._assignment(assignment_id)
        interviews = Interview.objects.filter(
            workspace_id=self.workspace_id,
            assignment=assignment,
        ).order_by("round_no")
        return [self._interview_output(interview) for interview in interviews]

    def update_interview(self, interview_id, data):
        interview = Interview.objects.filter(id=interview_id, workspace_id=self.workspace_id).first()
        if interview is None:
            raise NotFound404(404, "Resource not found")
        if "status" in data:
            if data["status"] not in InterviewStatus.values:
                raise AppApiException(400, "status is invalid")
            interview.status = data["status"]
        if "feedback" in data:
            interview.feedback = self._optional_string(data, "feedback", 4096)
        if "interviewer" in data:
            interview.interviewer = self._optional_string(data, "interviewer", 64)
        if "scheduled_at" in data:
            interview.scheduled_at = data["scheduled_at"] or None
        interview.save()
        return self._interview_output(interview)
