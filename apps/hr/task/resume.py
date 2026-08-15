# coding=utf-8
import os
from datetime import timedelta

import uuid_utils.compat as uuid
from celery_once import QueueOnce
from django.db import transaction
from django.utils import timezone
from celery.signals import worker_ready

from hr.models import Candidate, ResumeFile, ResumeStatus
from hr.services.audit import write_audit_log
from hr.services.resume_parser import extract_text_from_docx, extract_text_from_txt, parse_resume_text
from ops import celery_app

_SYSTEM_USER_ID = uuid.UUID(int=0)


@worker_ready.connect
def register_periodic_cleanup(sender=None, **kwargs):
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="3", day_of_week="*", day_of_month="*", month_of_year="*"
    )
    PeriodicTask.objects.get_or_create(
        name="hr-cleanup-orphan-resumes",
        defaults={"task": "hr.task.resume.cleanup_orphan_resumes", "crontab": crontab},
    )


@celery_app.task
def cleanup_orphan_resumes():
    cutoff = timezone.now() - timedelta(days=30)
    resumes = ResumeFile.objects.filter(candidate__isnull=True, create_time__lt=cutoff)
    for resume in resumes:
        file_delete_failed = False
        if resume.file_path and os.path.exists(resume.file_path):
            try:
                os.remove(resume.file_path)
            except OSError:
                file_delete_failed = True
        detail = "TTL cleanup: orphan resume older than 30 days"
        if file_delete_failed:
            detail += "; resume file removal failed"
        write_audit_log(
            resume.workspace_id, resume.user_id or _SYSTEM_USER_ID, "RESUME_DELETE", "RESUME", resume.id,
            result="FAILED" if file_delete_failed else "SUCCESS", detail=detail,
        )
        resume.delete()


@celery_app.task(base=QueueOnce, once={"keys": ["resume_id"]}, name="celery:hr_parse_resume")
def parse_resume_task(resume_id):
    resume = ResumeFile.objects.filter(id=resume_id).first()
    if resume is None:
        return
    try:
        if resume.extension == "docx":
            text = extract_text_from_docx(resume.file_path)
        else:
            text = extract_text_from_txt(resume.file_path)
        parsed = parse_resume_text(text)
        with transaction.atomic():
            candidate = Candidate.objects.create(
                workspace_id=resume.workspace_id,
                user_id=resume.user_id,
                name=parsed["name"] or resume.file_name,
                email=parsed["email"] or None,
                phone=parsed["phone"],
                current_city=parsed["current_city"],
                target_city=parsed["target_city"],
                highest_degree=parsed["highest_degree"],
                years_experience=parsed["years_experience"],
                skills=parsed["skills"],
                source=resume.source_channel,
                note=parsed["note"],
            )
            resume.candidate = candidate
            resume.status = ResumeStatus.SUCCESS
            resume.error_message = ""
            resume.save(update_fields=["candidate", "status", "error_message", "update_time"])
    except Exception as exc:
        resume.status = ResumeStatus.FAILED
        resume.error_message = str(exc)
        resume.save(update_fields=["status", "error_message", "update_time"])
