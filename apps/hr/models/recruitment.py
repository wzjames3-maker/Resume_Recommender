import uuid_utils.compat as uuid
from django.db import models
from django.db.models import Q
from django.utils import timezone


class CandidateStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class JobStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    OPEN = "OPEN", "Open"
    ON_HOLD = "ON_HOLD", "On hold"
    CLOSED = "CLOSED", "Closed"


class JobCloseReason(models.TextChoices):
    FILLED = "FILLED", "Filled"
    CANCELLED = "CANCELLED", "Cancelled"
    DUPLICATE = "DUPLICATE", "Duplicate"
    OTHER = "OTHER", "Other"


class AssignmentStatus(models.TextChoices):
    PENDING_SCREEN = "PENDING_SCREEN", "Pending screen"
    SCREEN_PASSED = "SCREEN_PASSED", "Screen passed"
    INTERVIEWING = "INTERVIEWING", "Interviewing"
    OFFER = "OFFER", "Offer"
    HIRED = "HIRED", "Hired"
    REJECTED = "REJECTED", "Rejected"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    CLOSED = "CLOSED", "Closed"


class TerminationReason(models.TextChoices):
    NOT_FIT = "NOT_FIT", "Not fit"
    SALARY = "SALARY", "Salary"
    UNREACHABLE = "UNREACHABLE", "Unreachable"
    CANDIDATE_WITHDRAW = "CANDIDATE_WITHDRAW", "Candidate withdraw"
    JOB_CLOSED = "JOB_CLOSED", "Job closed"
    MERGED = "MERGED", "Merged"
    OTHER = "OTHER", "Other"


class RelationType(models.TextChoices):
    APPLY = "APPLY", "Apply"
    SEEK = "SEEK", "Seek"
    REFERRAL = "REFERRAL", "Referral"
    HEADHUNTER = "HEADHUNTER", "Headhunter"


ACTIVE_ASSIGNMENT_STATUSES = [
    AssignmentStatus.PENDING_SCREEN,
    AssignmentStatus.SCREEN_PASSED,
    AssignmentStatus.INTERVIEWING,
    AssignmentStatus.OFFER,
]

TERMINAL_ASSIGNMENT_STATUSES = [
    AssignmentStatus.REJECTED,
    AssignmentStatus.WITHDRAWN,
    AssignmentStatus.CLOSED,
    AssignmentStatus.HIRED,
]


class ResumeChannel(models.TextChoices):
    REFERRAL = "REFERRAL", "Referral"
    JOB_SITE = "JOB_SITE", "Job site"
    HEADHUNTER = "HEADHUNTER", "Headhunter"
    CAMPUS = "CAMPUS", "Campus"
    OTHER = "OTHER", "Other"


class Candidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=128, db_index=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, default="")
    current_city = models.CharField(max_length=64, blank=True, default="")
    target_city = models.CharField(max_length=64, blank=True, default="")
    highest_degree = models.CharField(max_length=32, blank=True, default="")
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    skills = models.JSONField(default=list)
    source = models.CharField(max_length=64, blank=True, default="")
    note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=CandidateStatus.choices, default=CandidateStatus.ACTIVE)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_candidate"


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=128, db_index=True)
    department = models.CharField(max_length=128, blank=True, default="")
    city = models.CharField(max_length=64, blank=True, default="")
    level = models.CharField(max_length=64, blank=True, default="")
    headcount = models.PositiveSmallIntegerField(default=1)
    description = models.TextField(blank=True, default="")
    skill_requirements = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=JobStatus.choices, default=JobStatus.OPEN)
    close_reason = models.CharField(max_length=20, choices=JobCloseReason.choices, null=True, blank=True)
    owner_id = models.UUIDField(null=True, blank=True)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_job"
        constraints = [
            models.CheckConstraint(condition=Q(headcount__gte=1), name="hr_job_headcount_at_least_one")
        ]


class CandidateAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.PROTECT)
    job = models.ForeignKey(Job, on_delete=models.PROTECT)
    status = models.CharField(
        max_length=16,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.PENDING_SCREEN,
    )
    relation_type = models.CharField(max_length=16, choices=RelationType.choices, default=RelationType.APPLY)
    channel = models.CharField(max_length=20, choices=ResumeChannel.choices, default=ResumeChannel.OTHER)
    applied_at = models.DateTimeField(default=timezone.now)
    termination_reason = models.CharField(max_length=20, choices=TerminationReason.choices, null=True, blank=True)
    is_reapply = models.BooleanField(default=False)
    note = models.TextField(blank=True, default="")
    owner_id = models.UUIDField(null=True, blank=True)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_candidate_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "candidate", "job"],
                condition=Q(status__in=ACTIVE_ASSIGNMENT_STATUSES),
                name="hr_one_active_assignment_per_candidate_job",
            )
        ]


class InterviewStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PASSED = "PASSED", "Passed"
    FAILED = "FAILED", "Failed"
    NO_SHOW = "NO_SHOW", "No show"
    CANCELLED = "CANCELLED", "Cancelled"


class Interview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    assignment = models.ForeignKey(CandidateAssignment, on_delete=models.CASCADE)
    round_no = models.PositiveSmallIntegerField()
    interviewer = models.CharField(max_length=64, blank=True, default="")
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=InterviewStatus.choices, default=InterviewStatus.PENDING)
    feedback = models.TextField(blank=True, default="")
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_interview"


class ResumeStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"


class ResumeFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    file_name = models.CharField(max_length=255)
    extension = models.CharField(max_length=16)
    file_path = models.CharField(max_length=1024)
    file_size = models.IntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    source_channel = models.CharField(max_length=20, choices=ResumeChannel.choices, default=ResumeChannel.OTHER)
    status = models.CharField(max_length=16, choices=ResumeStatus.choices, default=ResumeStatus.PENDING)
    error_message = models.TextField(blank=True, default="")
    candidate = models.ForeignKey(Candidate, on_delete=models.SET_NULL, null=True, blank=True)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_resume_file"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "sha256"], name="hr_unique_resume_sha256_per_workspace")
        ]


class HrConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, unique=True)
    llm_model_id = models.CharField(max_length=128)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_config"


class HrRole(models.TextChoices):
    VIEWER = "VIEWER", "Viewer"
    OPERATOR = "OPERATOR", "Operator"
    ADMIN = "ADMIN", "Admin"


class HrAuditAction(models.TextChoices):
    VIEW_DETAIL = "VIEW_DETAIL", "View detail"
    CREATE = "CREATE", "Create"
    UPDATE = "UPDATE", "Update"
    ARCHIVE = "ARCHIVE", "Archive"
    RESTORE = "RESTORE", "Restore"
    DELETE = "DELETE", "Delete"
    JOB_CLOSE = "JOB_CLOSE", "Job close"
    JOB_REOPEN = "JOB_REOPEN", "Job reopen"
    ASSIGNMENT_TRANSITION = "ASSIGNMENT_TRANSITION", "Assignment transition"
    RESUME_UPLOAD = "RESUME_UPLOAD", "Resume upload"
    RESUME_DOWNLOAD = "RESUME_DOWNLOAD", "Resume download"
    RESUME_DELETE = "RESUME_DELETE", "Resume delete"
    MERGE = "MERGE", "Merge"
    GRANT_ACCESS = "GRANT_ACCESS", "Grant access"
    REVOKE_ACCESS = "REVOKE_ACCESS", "Revoke access"
    EXPORT = "EXPORT", "Export"
    ACCESS_DENIED = "ACCESS_DENIED", "Access denied"


class HrAuditObjectType(models.TextChoices):
    CANDIDATE = "CANDIDATE", "Candidate"
    JOB = "JOB", "Job"
    ASSIGNMENT = "ASSIGNMENT", "Assignment"
    RESUME = "RESUME", "Resume"
    HR_ACCESS = "HR_ACCESS", "HR access"
    OTHER = "OTHER", "Other"


class HrAuditResult(models.TextChoices):
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    DENIED = "DENIED", "Denied"


class HrAccess(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    user_id = models.UUIDField()
    role = models.CharField(max_length=16, choices=HrRole.choices, default=HrRole.VIEWER)

    class Meta:
        db_table = "hr_access"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "user_id"], name="hr_access_unique_workspace_user")
        ]


class HrAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    user_id = models.UUIDField()
    action = models.CharField(max_length=32, choices=HrAuditAction.choices)
    object_type = models.CharField(max_length=32, choices=HrAuditObjectType.choices, default=HrAuditObjectType.OTHER)
    object_id = models.CharField(max_length=64, blank=True, default="")
    result = models.CharField(max_length=8, choices=HrAuditResult.choices, default=HrAuditResult.SUCCESS)
    detail = models.TextField(blank=True, default="")
    create_time = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "hr_audit_log"
