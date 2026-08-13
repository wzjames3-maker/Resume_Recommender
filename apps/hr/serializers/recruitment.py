import hashlib
import os
import shutil

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    AssignmentStatus,
    Candidate,
    CandidateAssignment,
    CandidateStatus,
    Job,
    JobStatus,
    ResumeChannel,
    ResumeFile,
    ResumeStatus,
)
from hr.services.resume_parser import extract_text_from_docx, extract_text_from_txt, parse_resume_text
from maxkb.const import PROJECT_DIR


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
            "status": job.status,
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
        source = query.get("source")
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
        if years_min:
            try:
                years_min = int(years_min)
            except (TypeError, ValueError) as exc:
                raise AppApiException(400, "years_min is invalid") from exc
            queryset = queryset.filter(years_experience__gte=years_min)
        if source:
            queryset = queryset.filter(source=source)
        total = queryset.count()
        start = (current_page - 1) * page_size
        records = queryset.order_by("-update_time")[start:start + page_size]
        return {"total": total, "records": [self._candidate_output(candidate) for candidate in records]}

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
            status__in=[AssignmentStatus.PENDING_SCREEN, AssignmentStatus.SCREEN_PASSED],
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
            name=self._required_string(data, "name", 128),
            department=self._optional_string(data, "department", 128),
            city=self._optional_string(data, "city", 64),
            level=self._optional_string(data, "level", 64),
            headcount=headcount,
            description=self._optional_string(data, "description", 4096),
        )
        return self._job_output(job)

    def page_jobs(self, current_page, page_size, query):
        queryset = Job.objects.filter(workspace_id=self.workspace_id)
        name = query.get("name")
        status = query.get("status")
        if name:
            queryset = queryset.filter(name__icontains=name)
        if status:
            if status not in JobStatus.values:
                raise AppApiException(400, "status is invalid")
            queryset = queryset.filter(status=status)
        queryset = queryset.annotate(
            active_assignment_count=Count(
                "candidateassignment",
                filter=Q(candidateassignment__status__in=[
                    AssignmentStatus.PENDING_SCREEN,
                    AssignmentStatus.SCREEN_PASSED,
                ]),
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
        if "status" in data:
            if data["status"] not in JobStatus.values:
                raise AppApiException(400, "status is invalid")
            job.status = data["status"]
            update_fields.append("status")
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
        try:
            with transaction.atomic():
                assignment = CandidateAssignment.objects.create(
                    workspace_id=self.workspace_id,
                    user_id=self.user_id,
                    candidate=candidate,
                    job=job,
                    note=self._optional_string(data, "note", 4096),
                )
        except IntegrityError as exc:
            raise AppApiException(400, "An active assignment already exists") from exc
        return self._assignment_output(assignment)

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
                    if data["status"] in [AssignmentStatus.PENDING_SCREEN, AssignmentStatus.SCREEN_PASSED]:
                        candidate = Candidate.objects.select_for_update().get(id=assignment.candidate_id)
                        job = Job.objects.select_for_update().get(id=assignment.job_id)
                        if candidate.status != CandidateStatus.ACTIVE:
                            raise AppApiException(400, "Candidate is archived")
                        if job.status != JobStatus.OPEN:
                            raise AppApiException(400, "Job is closed")
                    assignment.status = data["status"]
                    update_fields.append("status")
                if "note" in data:
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
                })
                continue
            stored = os.path.join(self._resume_dir(), f"{sha256}.{extension}")
            shutil.move(file_path, stored)
            try:
                if extension == "docx":
                    text = extract_text_from_docx(stored)
                else:
                    text = extract_text_from_txt(stored)
                parsed = parse_resume_text(text)
                candidate = Candidate.objects.create(
                    workspace_id=self.workspace_id,
                    user_id=self.user_id,
                    name=parsed["name"] or file_name,
                    email=parsed["email"] or None,
                    phone=parsed["phone"],
                    current_city=parsed["current_city"],
                    target_city=parsed["target_city"],
                    highest_degree=parsed["highest_degree"],
                    years_experience=parsed["years_experience"],
                    skills=parsed["skills"],
                    source=source_channel,
                    note=parsed["note"],
                )
                resume = ResumeFile.objects.create(
                    workspace_id=self.workspace_id, file_name=file_name, extension=extension,
                    file_path=stored, file_size=size, sha256=sha256,
                    source_channel=source_channel, status=ResumeStatus.SUCCESS, candidate=candidate,
                    user_id=self.user_id,
                )
            except Exception as exc:
                resume = ResumeFile.objects.create(
                    workspace_id=self.workspace_id, file_name=file_name, extension=extension,
                    file_path=stored, file_size=size, sha256=sha256,
                    source_channel=source_channel, status=ResumeStatus.FAILED,
                    error_message=str(exc), user_id=self.user_id,
                )
            records.append({
                "resume_id": str(resume.id),
                "file_name": resume.file_name,
                "status": resume.status,
                "sha256": resume.sha256,
                "duplicate": False,
                "candidate_id": str(resume.candidate_id) if resume.candidate_id else None,
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
