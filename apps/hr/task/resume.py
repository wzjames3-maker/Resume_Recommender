# coding=utf-8
from celery_once import QueueOnce
from django.db import transaction

from hr.models import Candidate, ResumeFile, ResumeStatus
from hr.services.resume_parser import extract_text_from_docx, extract_text_from_txt, parse_resume_text
from ops import celery_app


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
