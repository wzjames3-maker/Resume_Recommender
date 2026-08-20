import uuid_utils.compat as uuid
from django.db import models
from django.db.models import Q
from django.utils import timezone


class CandidateStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"
    DELETED = "DELETED", "Deleted"


class ConsentStatus(models.TextChoices):
    UNKNOWN = "UNKNOWN", "Unknown"
    NOTIFIED = "NOTIFIED", "Notified"
    CONSENTED = "CONSENTED", "Consented"
    NOT_REQUIRED = "NOT_REQUIRED", "Not required"


class ContactPreference(models.TextChoices):
    EMAIL = "EMAIL", "Email"
    PHONE = "PHONE", "Phone"
    NO_CONTACT = "NO_CONTACT", "No contact"
    UNSPECIFIED = "UNSPECIFIED", "Unspecified"


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
    source_type = models.CharField(max_length=20, choices=ResumeChannel.choices, default=ResumeChannel.OTHER)
    source_detail = models.CharField(max_length=128, blank=True, default="")
    collected_at = models.DateTimeField(null=True, blank=True)
    consent_status = models.CharField(max_length=16, choices=ConsentStatus.choices, default=ConsentStatus.UNKNOWN)
    consent_version = models.CharField(max_length=32, blank=True, default="")
    contact_preference = models.CharField(
        max_length=16, choices=ContactPreference.choices, default=ContactPreference.UNSPECIFIED
    )
    note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=CandidateStatus.choices, default=CandidateStatus.ACTIVE)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_candidate"


class CandidateSkill(models.Model):
    """技能归一表（T5）：candidate.skills 的归一化展平，支撑 Skill-AND 的 SQL 精确匹配。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="skill_rows")
    skill_norm = models.CharField(max_length=128, db_index=True)
    skill_raw = models.CharField(max_length=128)

    class Meta:
        db_table = "hr_candidate_skill"
        constraints = [
            models.UniqueConstraint(fields=["candidate", "skill_norm"], name="hr_candidate_skill_uniq")
        ]


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


class InterviewStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PASSED = "PASSED", "Passed"
    FAILED = "FAILED", "Failed"
    NO_SHOW = "NO_SHOW", "No show"
    CANCELLED = "CANCELLED", "Cancelled"


class OfferStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SENT = "SENT", "Sent"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


class OfferApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class Offer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    application = models.ForeignKey("Application", on_delete=models.CASCADE, null=True, blank=True, related_name="offers")
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    version = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, choices=OfferStatus.choices, default=OfferStatus.DRAFT)
    salary_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=16, default="CNY")
    approval_status = models.CharField(
        max_length=16, choices=OfferApprovalStatus.choices, default=OfferApprovalStatus.PENDING
    )
    approver_id = models.UUIDField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    attachment_name = models.CharField(max_length=255, blank=True, default="")
    attachment_path = models.CharField(max_length=1024, blank=True, default="")
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_offer"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "application", "version"], name="hr_unique_offer_version_per_application"
            ),
        ]


class HandoffStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"


class HandoffTargetType(models.TextChoices):
    CHECKLIST = "CHECKLIST", "Checklist"
    WEBHOOK = "WEBHOOK", "Webhook"


class OnboardingHandoff(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    application = models.ForeignKey("Application", on_delete=models.CASCADE, null=True, blank=True, related_name="handoffs")
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, choices=HandoffStatus.choices, default=HandoffStatus.PENDING)
    payload = models.TextField(blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    handoff_time = models.DateTimeField(null=True, blank=True)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_onboarding_handoff"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "application"], name="hr_unique_handoff_per_application"
            ),
        ]


class Interview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    application = models.ForeignKey("Application", on_delete=models.CASCADE, null=True, blank=True, related_name="interviews")
    round_no = models.PositiveSmallIntegerField()
    interviewer = models.CharField(max_length=64, blank=True, default="")
    interviewer_user_id = models.UUIDField(null=True, blank=True)
    feedback_deadline = models.DateTimeField(null=True, blank=True)
    feedback_submitted_at = models.DateTimeField(null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=InterviewStatus.choices, default=InterviewStatus.PENDING)
    feedback = models.TextField(blank=True, default="")
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_interview"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "application", "round_no"], name="hr_unique_interview_round_per_application"
            ),
        ]


class ResumeDatabaseStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class ResumeDatabase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=128)
    description = models.CharField(max_length=512, blank=True, default="")
    status = models.CharField(max_length=16, choices=ResumeDatabaseStatus.choices, default=ResumeDatabaseStatus.ACTIVE)
    is_default = models.BooleanField(default=False)
    is_system = models.BooleanField(default=False)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_resume_database"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "name"], name="hr_resume_database_workspace_name_uniq"),
        ]


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
    resume_database = models.ForeignKey(ResumeDatabase, on_delete=models.PROTECT, related_name="resume_files")
    status = models.CharField(max_length=16, choices=ResumeStatus.choices, default=ResumeStatus.PENDING)
    error_message = models.TextField(blank=True, default="")
    raw_text = models.TextField(blank=True, default="", verbose_name="docx/txt 提取原文（混合检索关键字腿）")
    candidate = models.ForeignKey(Candidate, on_delete=models.SET_NULL, null=True, blank=True)
    document_id = models.UUIDField(null=True, blank=True, verbose_name="语义索引文档id")
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # 低层导入/管理命令也必须遵守总库归属，避免绕过上传服务产生无范围简历。
        if not kwargs.get("raw") and self.workspace_id:
            total = ResumeDatabase.objects.filter(
                workspace_id=self.workspace_id, status=ResumeDatabaseStatus.ACTIVE, is_system=True
            ).first()
            if total is None:
                total = ResumeDatabase.objects.filter(
                    workspace_id=self.workspace_id, status=ResumeDatabaseStatus.ACTIVE, is_default=True
                ).first()
            if total is None:
                total = ResumeDatabase.objects.create(
                    workspace_id=self.workspace_id, name="总库", is_default=True, is_system=True
                )
            if not total.is_system:
                total.is_system = True
                total.save(update_fields=["is_system", "update_time"])
            if not self.resume_database_id:
                self.resume_database = total
        super().save(*args, **kwargs)
        membership_model = globals().get("ResumeDatabaseMembership")
        if not kwargs.get("raw") and membership_model and self.resume_database_id and self.workspace_id:
            total = ResumeDatabase.objects.filter(
                workspace_id=self.workspace_id, status=ResumeDatabaseStatus.ACTIVE, is_system=True
            ).first()
            if total is not None:
                membership_model.objects.get_or_create(resume_file=self, resume_database=total)

    class Meta:
        db_table = "hr_resume_file"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "sha256"], name="hr_unique_resume_sha256_per_workspace")
        ]


class ResumeDatabaseMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    resume_file = models.ForeignKey(ResumeFile, on_delete=models.CASCADE, related_name="database_memberships")
    resume_database = models.ForeignKey(ResumeDatabase, on_delete=models.CASCADE, related_name="resume_memberships")
    create_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hr_resume_database_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["resume_file", "resume_database"], name="hr_resume_database_membership_uniq"
            ),
        ]


class HrConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, unique=True)
    llm_model_id = models.CharField(max_length=128)
    rerank_model_id = models.CharField(max_length=128, blank=True, default="", verbose_name="重排序模型id")
    handoff_target_type = models.CharField(
        max_length=16, choices=HandoffTargetType.choices, default=HandoffTargetType.CHECKLIST
    )
    handoff_webhook_url = models.CharField(max_length=512, blank=True, default="")
    agent_enable_screening = models.BooleanField(default=False, verbose_name="Screening Agent 开关")
    agent_max_concurrent_runs = models.PositiveSmallIntegerField(default=2, verbose_name="Agent 并发运行上限")
    agent_run_rate_limit = models.PositiveSmallIntegerField(default=10, verbose_name="Agent 每小时触发上限")
    agent_score_version = models.CharField(max_length=32, default="v1", verbose_name="评分函数版本")
    agent_score_bands = models.JSONField(default=dict, verbose_name="评分分带（advance/hold）")
    agent_knowledge_bases = models.JSONField(
        default=list, verbose_name="Agent 可用企业知识库白名单（id 列表）"
    )
    agent_prompt_versions = models.JSONField(default=dict, verbose_name="Agent 提示词生效版本（只读）")
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_config"





class ResumeFlowLog(models.Model):
    """简历数据流转日志：记录每个处理节点的流转数据（可追溯/可审计）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    resume_id = models.UUIDField(null=True, blank=True, db_index=True)
    candidate_id = models.UUIDField(null=True, blank=True)
    document_id = models.UUIDField(null=True, blank=True)
    node = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=16, default="SUCCESS")
    detail = models.JSONField(default=dict)
    error_message = models.TextField(blank=True, default="")
    create_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hr_resume_flow_log"
        indexes = [models.Index(fields=["workspace_id", "resume_id", "create_time"], name="hr_resume_flow_ws_rs_time_idx")]


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
    INTERVIEW_FEEDBACK = "INTERVIEW_FEEDBACK", "Interview feedback"
    OFFER_SEND = "OFFER_SEND", "Offer send"
    OFFER_ACCEPT = "OFFER_ACCEPT", "Offer accept"
    OFFER_REJECT = "OFFER_REJECT", "Offer reject"
    OFFER_WITHDRAW = "OFFER_WITHDRAW", "Offer withdraw"
    OFFER_APPROVE = "OFFER_APPROVE", "Offer approve"
    HANDOFF = "HANDOFF", "Handoff"
    IMPORT = "IMPORT", "Import"
    MERGE = "MERGE", "Merge"
    GRANT_ACCESS = "GRANT_ACCESS", "Grant access"
    REVOKE_ACCESS = "REVOKE_ACCESS", "Revoke access"
    EXPORT = "EXPORT", "Export"
    SEARCH = "SEARCH", "Resume semantic search"
    AGENT_RUN = "AGENT_RUN", "Agent run"
    AGENT_DECIDE = "AGENT_DECIDE", "Agent decide"
    ACCESS_DENIED = "ACCESS_DENIED", "Access denied"


class HrAuditObjectType(models.TextChoices):
    CANDIDATE = "CANDIDATE", "Candidate"
    JOB = "JOB", "Job"
    ASSIGNMENT = "ASSIGNMENT", "Assignment"
    APPLICATION = "APPLICATION", "Application"
    INTERVIEW = "INTERVIEW", "Interview"
    OFFER = "OFFER", "Offer"
    ONBOARDING = "ONBOARDING", "Onboarding"
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
    trace_id = models.CharField(max_length=64, blank=True, default="")
    create_time = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "hr_audit_log"


class ApplicationStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    HIRED = "HIRED", "Hired"
    REJECTED = "REJECTED", "Rejected"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    CLOSED = "CLOSED", "Closed"


class ApplicationEventType(models.TextChoices):
    CREATED = "CREATED", "Created"
    IMPORTED = "IMPORTED", "Imported"
    STAGE_MOVED = "STAGE_MOVED", "Stage moved"
    HIRED = "HIRED", "Hired"
    REJECTED = "REJECTED", "Rejected"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    CLOSED = "CLOSED", "Closed"
    RESTORED = "RESTORED", "Restored"


class JobStage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="stages")
    key = models.CharField(max_length=32)
    name = models.CharField(max_length=64)
    color = models.CharField(max_length=16, blank=True, default="")
    order = models.PositiveSmallIntegerField()
    is_system = models.BooleanField(default=False)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_job_stage"
        constraints = [
            models.UniqueConstraint(fields=["job", "order"], name="hr_job_stage_job_order_uniq"),
            models.UniqueConstraint(fields=["job", "key"], name="hr_job_stage_job_key_uniq"),
            models.UniqueConstraint(fields=["job", "name"], name="hr_job_stage_job_name_uniq"),
        ]


class Application(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.PROTECT, related_name="applications")
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="applications")
    current_stage = models.ForeignKey(JobStage, on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(max_length=16, choices=ApplicationStatus.choices, default=ApplicationStatus.ACTIVE)
    relation_type = models.CharField(max_length=16, choices=RelationType.choices, default=RelationType.APPLY)
    channel = models.CharField(max_length=20, choices=ResumeChannel.choices, default=ResumeChannel.OTHER)
    channel_detail = models.CharField(max_length=128, blank=True, default="")
    applied_at = models.DateTimeField(default=timezone.now)
    owner_id = models.UUIDField(null=True, blank=True)
    recruiter_id = models.UUIDField(null=True, blank=True)
    termination_reason = models.CharField(max_length=20, choices=TerminationReason.choices, null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)
    reapply_of = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True)
    reapply_no = models.PositiveSmallIntegerField(default=0)
    rehire_confirmed = models.BooleanField(default=False)
    rehire_reason = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_application"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "candidate", "job"],
                condition=Q(status=ApplicationStatus.ACTIVE),
                name="hr_application_one_active_per_candidate_job",
            )
        ]


class ApplicationEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=32, choices=ApplicationEventType.choices)
    from_stage = models.ForeignKey(JobStage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    to_stage = models.ForeignKey(JobStage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16, blank=True, default="")
    actor_id = models.UUIDField(null=True, blank=True)
    reason_code = models.CharField(max_length=32, blank=True, default="")
    reason_text = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=128, blank=True, default="")
    trace_id = models.CharField(max_length=64, blank=True, default="")
    create_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hr_application_event"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "application", "event_type", "idempotency_key"],
                name="hr_application_event_idempotency_uniq",
            )
        ]


class HrAgentType(models.TextChoices):
    SCREENING = "SCREENING", "Screening"
    JD_DRAFT = "JD_DRAFT", "JD Draft"
    INTERVIEW_COPILOT = "INTERVIEW_COPILOT", "Interview Copilot"
    SOURCING = "SOURCING", "Sourcing"
    COMMUNICATION_DRAFT = "COMMUNICATION_DRAFT", "Communication Draft"


class HrAgentTriggerType(models.TextChoices):
    EVENT = "EVENT", "Event"
    MANUAL = "MANUAL", "Manual"


class HrAgentRunStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    RUNNING = "RUNNING", "Running"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"


class HrAgentRun(models.Model):
    """Agent 运行账本：输入摘要 / 工具轨迹 / 输出 / 成本 / 失败，全量留痕（PRD-AGENT-RAG §4.3）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    agent_type = models.CharField(max_length=32, choices=HrAgentType.choices, default=HrAgentType.SCREENING)
    trigger_type = models.CharField(max_length=16, choices=HrAgentTriggerType.choices, default=HrAgentTriggerType.EVENT)
    ref_object_type = models.CharField(max_length=32, default="APPLICATION")
    ref_object_id = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=16, choices=HrAgentRunStatus.choices, default=HrAgentRunStatus.PENDING)
    input_meta = models.JSONField(default=dict)
    tool_trace = models.JSONField(default=list)
    output_json = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    llm_model = models.CharField(max_length=128, blank=True, default="")
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    prompt_version = models.CharField(max_length=32, blank=True, default="")
    duration_ms = models.IntegerField(default=0)
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_agent_run"
        indexes = [
            models.Index(fields=["workspace_id", "agent_type", "status"], name="hr_agent_run_ws_type_status"),
            models.Index(fields=["workspace_id", "ref_object_id"], name="hr_agent_run_ws_ref_idx"),
        ]


class HrAgentProposalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    DISMISSED = "DISMISSED", "Dismissed"
    EXPIRED = "EXPIRED", "Expired"


class HrAgentProposalAction(models.TextChoices):
    ADVANCE = "ADVANCE", "Advance"
    DECLINE = "DECLINE", "Decline"
    HOLD = "HOLD", "Hold"
    DRAFT = "DRAFT", "Draft"


class HrAgentProposal(models.Model):
    """Agent 提议工件（唯一写出口）：PENDING → ACCEPTED / DISMISSED / EXPIRED。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, db_index=True)
    run = models.ForeignKey(HrAgentRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="proposals")
    target_type = models.CharField(max_length=32, default="APPLICATION")
    target_id = models.CharField(max_length=64, db_index=True)
    action = models.CharField(max_length=16, choices=HrAgentProposalAction.choices)
    payload_json = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=HrAgentProposalStatus.choices, default=HrAgentProposalStatus.PENDING
    )
    decided_by = models.UUIDField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_agent_proposal"
        indexes = [
            models.Index(
                fields=["workspace_id", "target_type", "target_id", "status"],
                name="hr_agent_proposal_ws_target_st",
            )
        ]


class HrOffboard(models.Model):
    """HR 工作区注销账本（tombstone）：注销后唯一保留的 HR 记录。

    既是幂等锚点（workspace_id 唯一，重复执行报已注销），也是注销留痕
    （执行人 / 时间 / 各表计数 / 数据返还包路径），满足设计验收「注销全程留痕」。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, unique=True)
    offboarded_at = models.DateTimeField(auto_now_add=True)
    user_id = models.UUIDField(null=True, blank=True)
    exported_path = models.CharField(max_length=1024, blank=True, default="")
    counts = models.JSONField(default=dict)
    force = models.BooleanField(default=False)

    class Meta:
        db_table = "hr_offboard"
