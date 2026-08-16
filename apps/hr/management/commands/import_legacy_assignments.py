# coding=utf-8
"""
    @project: MaxKB
    @file： import_legacy_assignments.py
    @date：2026/8/17
    @desc: 一次性数据迁移命令：存量 CandidateAssignment → Application（ATS v2）。

    映射规则（docs/ATS-STATE-MACHINE-V2.md §7）：
      PENDING_SCREEN → Stage=APPLIED, status=ACTIVE
      SCREEN_PASSED  → Stage=SCREEN,  status=ACTIVE
      INTERVIEWING   → Stage=INTERVIEW, status=ACTIVE
      OFFER          → Stage=OFFER,   status=ACTIVE
      HIRED          → 最后阶段, status=HIRED
      REJECTED       → 最后阶段, status=REJECTED
      WITHDRAWN      → 最后阶段, status=WITHDRAWN
      CLOSED         → 最后阶段, status=CLOSED

    幂等：每个存量指派生成一条 ApplicationEvent(IMPORTED, idempotency_key="import:{assignment_id}")，
    已存在该事件即跳过；可重复执行。执行前请备份数据库。
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from hr.models import (
    Application,
    ApplicationEvent,
    ApplicationEventType,
    ApplicationStatus,
    AssignmentStatus,
    CandidateAssignment,
    Interview,
    Job,
    JobStage,
    Offer,
    OnboardingHandoff,
    TerminationReason,
)
from hr.services.application_service import create_default_stages

# 旧指派状态 → (新阶段 key, 新 status)
_STATUS_MAP = {
    AssignmentStatus.PENDING_SCREEN: ("APPLIED", ApplicationStatus.ACTIVE),
    AssignmentStatus.SCREEN_PASSED: ("SCREEN", ApplicationStatus.ACTIVE),
    AssignmentStatus.INTERVIEWING: ("INTERVIEW", ApplicationStatus.ACTIVE),
    AssignmentStatus.OFFER: ("OFFER", ApplicationStatus.ACTIVE),
    AssignmentStatus.HIRED: (None, ApplicationStatus.HIRED),
    AssignmentStatus.REJECTED: (None, ApplicationStatus.REJECTED),
    AssignmentStatus.WITHDRAWN: (None, ApplicationStatus.WITHDRAWN),
    AssignmentStatus.CLOSED: (None, ApplicationStatus.CLOSED),
}

# 终态默认终止原因（旧表无原因时兜底，不丢语义）
_DEFAULT_REASON = {
    ApplicationStatus.REJECTED: TerminationReason.OTHER,
    ApplicationStatus.WITHDRAWN: TerminationReason.OTHER,
    ApplicationStatus.CLOSED: TerminationReason.JOB_CLOSED,
}


class Command(BaseCommand):
    help = "将存量 CandidateAssignment 迁移为 Application（幂等，可重复执行；建议先备份）"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="只统计不落库")
        parser.add_argument("--workspace", default=None, help="仅迁移指定 workspace_id")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        workspace = options["workspace"]

        assignments = CandidateAssignment.objects.select_related("candidate", "job").order_by("create_time")
        if workspace:
            assignments = assignments.filter(workspace_id=workspace)

        # 1) 确保每个 Job 有默认 Pipeline（R1 之前创建的 Job 没有 JobStage）
        job_ids = list(assignments.values_list("job_id", flat=True).distinct())
        if not dry_run:
            for job in Job.objects.filter(id__in=job_ids):
                if not JobStage.objects.filter(job=job).exists():
                    create_default_stages(job.workspace_id, job)

        imported = 0
        skipped = 0
        by_workspace_candidate_job = {}
        mapping = {}

        for assignment in assignments:
            marker = f"import:{assignment.id}"
            if ApplicationEvent.objects.filter(
                event_type=ApplicationEventType.IMPORTED, idempotency_key=marker
            ).exists():
                existing = Application.objects.filter(
                    workspace_id=assignment.workspace_id,
                    candidate_id=assignment.candidate_id,
                    job_id=assignment.job_id,
                ).order_by("create_time").first()
                if existing is not None:
                    mapping[str(assignment.id)] = existing
                skipped += 1
                continue

            stage_key, status = _STATUS_MAP.get(assignment.status, (None, ApplicationStatus.ACTIVE))
            stages = list(JobStage.objects.filter(job_id=assignment.job_id).order_by("order"))
            if not stages:
                self.stderr.write(f"跳过：job {assignment.job_id} 无 Pipeline")
                skipped += 1
                continue
            if stage_key is None:
                # 终态保留最后阶段
                stage = stages[-1]
            else:
                stage = next((s for s in stages if s.key == stage_key), stages[0])
            terminal = status != ApplicationStatus.ACTIVE
            key = (assignment.workspace_id, str(assignment.candidate_id), str(assignment.job_id))
            previous = by_workspace_candidate_job.get(key)
            reapply_no = (previous.reapply_no if previous else 0) + 1
            terminated_at = assignment.update_time if terminal else None
            termination_reason = (
                assignment.termination_reason
                if terminal and assignment.termination_reason
                else (_DEFAULT_REASON.get(status) if terminal else None)
            )
            if dry_run:
                imported += 1
                by_workspace_candidate_job[key] = type("_T", (), {"reapply_no": reapply_no})
                continue

            with transaction.atomic():
                application = Application.objects.create(
                    workspace_id=assignment.workspace_id,
                    user_id=assignment.user_id,
                    candidate_id=assignment.candidate_id,
                    job_id=assignment.job_id,
                    current_stage=stage,
                    status=status,
                    relation_type=assignment.relation_type,
                    channel=assignment.channel,
                    applied_at=assignment.applied_at,
                    owner_id=assignment.owner_id,
                    recruiter_id=assignment.owner_id,
                    termination_reason=termination_reason,
                    terminated_at=terminated_at,
                    reapply_of=previous,
                    reapply_no=reapply_no,
                    note=assignment.note,
                )
                ApplicationEvent.objects.create(
                    workspace_id=assignment.workspace_id,
                    application=application,
                    event_type=ApplicationEventType.IMPORTED,
                    from_stage=None,
                    to_stage=stage,
                    from_status="",
                    to_status=status,
                    actor_id=None,
                    reason_code=assignment.status,
                    reason_text=f"migrated from CandidateAssignment {assignment.id}",
                    idempotency_key=marker,
                    trace_id="",
                )
            by_workspace_candidate_job[key] = application
            mapping[str(assignment.id)] = application
            imported += 1

        # 2) 回填 Interview / Offer / Handoff 的 application_id
        linked = 0
        if not dry_run and mapping:
            for model in (Interview, Offer, OnboardingHandoff):
                rows = model.objects.filter(assignment_id__in=list(mapping.keys()), application_id__isnull=True)
                for row in rows:
                    row.application_id = mapping[str(row.assignment_id)].id
                    row.save(update_fields=["application_id", "update_time"])
                    linked += 1

        self.stdout.write(
            self.style.SUCCESS(f"imported={imported} skipped={skipped} linked_sub_objects={linked}"
                               + (" (dry-run)" if dry_run else ""))
        )
