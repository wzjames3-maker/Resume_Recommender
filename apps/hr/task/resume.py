# coding=utf-8
import time
from datetime import timedelta

from django.db.models import QuerySet

import uuid_utils.compat as uuid
from celery_once import QueueOnce
from django.db import transaction
from django.utils import timezone
from celery.signals import worker_ready

from hr.models import Candidate, HrConfig, ResumeFile, ResumeStatus
from knowledge.models import Document, Paragraph
from hr.services.audit import write_audit_log
from hr.services.flow_log import log_flow
from hr.services.resume_index import ResidualPIIError, delete_resume_index, index_resume
from hr.services.resume_parser import extract_text_from_docx, extract_text_from_txt, parse_resume_text
from hr.services.resume_splitter import sanitize_resume_text, split_resume_with_skills
from models_provider.tools import get_model_instance_by_model_workspace_id
from hr.services.storage import get_storage
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
        # 语义索引联动清理（幂等；仅已索引的孤儿简历有 document_id）
        delete_resume_index(resume)
        # P1-13: 同步清理流转日志（EXTRACT/SANITIZE 含未脱敏全文，避免 PII 永久留存）
        try:
            from hr.services.flow_log import delete_flow_logs

            delete_flow_logs(resume.workspace_id, resume.id)
        except Exception:
            pass
        file_delete_failed = False
        if resume.file_path and get_storage().exists(resume.file_path):
            try:
                get_storage().delete(resume.file_path)
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
        local_path = get_storage().open(resume.file_path)
        if resume.extension == "docx":
            text = extract_text_from_docx(local_path)
        else:
            text = extract_text_from_txt(local_path)
        log_flow(
            resume.workspace_id, "EXTRACT", resume_id=resume.id,
            detail={"length": len(text), "lines": text.count("\n") + 1, "source": resume.extension},
        )
        parsed = parse_resume_text(text)
        # 设计：LLM 只负责切片；技能/城市/学历等字段不做规则解析（正则只抽姓名/电话/邮箱），
        # 统一由切片与混合检索（关键字+稀疏+密集）按需处理。
        # 预切片为空时回退 _index_resume 内部切片；失败不阻塞建档。
        chat_fn = _llm_chat_fn(resume.workspace_id)
        pre_split = None
        if chat_fn is not None:
            try:
                chunks, _, split_stats = split_resume_with_skills(text, chat_fn)
                pre_split = {"chunks": chunks, "stats": split_stats}
            except Exception:
                pre_split = None
        with transaction.atomic():
            candidate = Candidate.objects.create(
                workspace_id=resume.workspace_id,
                user_id=resume.user_id,
                name=parsed["name"] or resume.file_name,
                email=parsed["email"] or None,
                phone=parsed["phone"],
            )
            resume.candidate = candidate
            resume.status = ResumeStatus.SUCCESS
            resume.error_message = ""
            resume.raw_text = text
            resume.save(update_fields=["candidate", "status", "error_message", "raw_text", "update_time"])
        _index_resume(
            resume, text,
            chunks=(pre_split or {}).get("chunks"),
            split_stats=(pre_split or {}).get("stats"),
        )
    except Exception as exc:
        resume.status = ResumeStatus.FAILED
        resume.error_message = str(exc)
        resume.save(update_fields=["status", "error_message", "update_time"])


def _llm_chat_fn(workspace_id):
    """按工作区 HR AI 配置取 LLM 模型适配器；未配置返回 None。"""
    config = HrConfig.objects.filter(workspace_id=workspace_id).first()
    if config is None or not config.llm_model_id:
        return None
    try:
        model = get_model_instance_by_model_workspace_id(config.llm_model_id, workspace_id)
    except Exception:
        return None
    return lambda prompt: model.invoke(prompt).content


def _index_resume(resume, text, chunks=None, split_stats=None):
    """
    简历语义索引（清洗→切片→建文档→向量化）。失败只记录 error_message，不阻塞候选人建档。
    每个节点写流转日志（ResumeFlowLog）。
    """
    chat_fn = _llm_chat_fn(resume.workspace_id)
    if chat_fn is None and chunks is None:
        log_flow(resume.workspace_id, "SPLIT", status="FAILED", resume_id=resume.id,
                 error_message="HR AI 模型未配置，无法切片")
        resume.error_message = "语义索引失败: HR AI 模型未配置"
        resume.save(update_fields=["error_message", "update_time"])
        return
    try:
        cleaned = sanitize_resume_text(text)
        log_flow(
            resume.workspace_id, "SANITIZE", resume_id=resume.id,
            detail={"before": len(text), "after": len(cleaned), "cleaned": cleaned},
        )
        stats = dict(split_stats) if split_stats else {}
        started = time.time()
        document_id = index_resume(
            resume.workspace_id, resume.user_id or _SYSTEM_USER_ID, resume, cleaned, chat_fn,
            stats=stats, chunks=chunks,
        )
        document = QuerySet(Document).filter(id=document_id).first()
        log_flow(
            resume.workspace_id, "DOCUMENT", resume_id=resume.id, document_id=document_id,
            detail={
                "path": stats.get("path", "?"),
                "llm_calls": stats.get("llm_calls", 0),
                "paragraphs": QuerySet(Paragraph).filter(document_id=document_id).count() if document else 0,
                "knowledge_id": str(document.knowledge_id) if document else None,
                "elapsed_ms": int((time.time() - started) * 1000),
            },
        )
        resume.error_message = ""
        resume.save(update_fields=["error_message", "update_time"])
    except Exception as exc:
        if not isinstance(exc, ResidualPIIError):
            # 残留 PII 拒绝已在 index_resume 内记录 SPLIT FAILED（含 path/llm_calls 详情），不重复写日志
            log_flow(resume.workspace_id, "SPLIT", status="FAILED", resume_id=resume.id, error_message=str(exc))
        resume.error_message = f"语义索引失败: {exc}"
        resume.save(update_fields=["error_message", "update_time"])
