import uuid_utils.compat as uuid
from django.db import models
from django.db.models import Q


class CandidateStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class JobStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"


class AssignmentStatus(models.TextChoices):
    PENDING_SCREEN = "PENDING_SCREEN", "Pending screen"
    SCREEN_PASSED = "SCREEN_PASSED", "Screen passed"
    REJECTED = "REJECTED", "Rejected"
    CLOSED = "CLOSED", "Closed"


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
    status = models.CharField(max_length=16, choices=JobStatus.choices, default=JobStatus.OPEN)
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
    note = models.TextField(blank=True, default="")
    user_id = models.UUIDField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_candidate_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "candidate", "job"],
                condition=Q(status__in=[AssignmentStatus.PENDING_SCREEN, AssignmentStatus.SCREEN_PASSED]),
                name="hr_one_active_assignment_per_candidate_job",
            )
        ]
