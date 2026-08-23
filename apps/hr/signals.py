# coding=utf-8
"""
    @project: MaxKB
    @file： signals.py
    @date：2026/8/17
    @desc: ATS v2 事件触发（PRD-AGENT-RAG §4.1）：新建 Application（ACTIVE + APPLIED + APPLY/REFERRAL）
           且工作区开启 Screening Agent 时，异步分发初筛评估任务（不阻塞业务请求）。
"""
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from hr.models import Application, ApplicationStatus, Candidate, HrConfig, RelationType, ResumeFile


@receiver(post_save, sender=Application)
def application_created(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.status != ApplicationStatus.ACTIVE:
        return
    if instance.relation_type not in (RelationType.APPLY, RelationType.REFERRAL):
        return
    if instance.current_stage_id is None:
        return
    config = HrConfig.objects.filter(workspace_id=instance.workspace_id).only("agent_enable_screening").first()
    if config is None or not config.agent_enable_screening:
        return
    from hr.agents.runner import dispatch_event_screening

    try:
        # 事务提交后再投递，避免 worker 先于 COMMIT 拾取导致静默丢失或幻影任务（P2-11）
        transaction.on_commit(lambda: dispatch_event_screening(instance.id))
    except Exception as exc:
        # 事件触发失败不影响业务请求；后续可人工触发
        import logging
        logging.getLogger("hr").warning("Screening dispatch failed for application %s: %s", instance.id, exc)


def _cleanup_resume_artifacts(resume, save):
    """旁路删除兜底：清理简历语义索引与流转日志（均幂等；失败不阻塞删除事务）。"""
    import logging

    from hr.services.flow_log import delete_flow_logs
    from hr.services.resume_index import delete_resume_index

    try:
        delete_resume_index(resume, save=save)
    except Exception as exc:
        logging.getLogger("hr").warning("Resume index cleanup failed for resume %s: %s", resume.id, exc)
    try:
        delete_flow_logs(resume.workspace_id, resume.id)
    except Exception as exc:
        logging.getLogger("hr").warning("Flow log cleanup failed for resume %s: %s", resume.id, exc)


@receiver(pre_delete, sender=Candidate)
def candidate_pre_delete_collect_resumes(sender, instance, **kwargs):
    """Collector 先对 ResumeFile.candidate 应用 SET_NULL、再删候选人行并发 post_delete，
    届时已无法按 candidate 反查，须在 pre_delete 记录待清理的简历 id。"""
    instance._hr_pending_resume_ids = list(
        ResumeFile.objects.filter(candidate_id=instance.id).values_list("id", flat=True)
    )


@receiver(post_delete, sender=Candidate)
def candidate_post_delete_cleanup(sender, instance, **kwargs):
    """旁路删除（绕过 serializer）删除候选人时，其简历已被置为孤儿——立即清理
    语义索引与含未脱敏全文的流转日志，不留存至 30 天 TTL。"""
    for resume in ResumeFile.objects.filter(id__in=getattr(instance, "_hr_pending_resume_ids", ())):
        _cleanup_resume_artifacts(resume, save=True)


@receiver(post_delete, sender=ResumeFile)
def resume_file_post_delete_cleanup(sender, instance, **kwargs):
    """旁路删除（绕过 serializer，如 queryset.delete/admin）时兜底清理向量与流转日志；
    行已删除，save=False 避免回写报错。serializer 正常路径先行清理过，此处幂等空跑。"""
    _cleanup_resume_artifacts(instance, save=False)
