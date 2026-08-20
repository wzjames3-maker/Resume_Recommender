# coding=utf-8
"""
    @project: MaxKB
    @file： signals.py
    @date：2026/8/17
    @desc: ATS v2 事件触发（PRD-AGENT-RAG §4.1）：新建 Application（ACTIVE + APPLIED + APPLY/REFERRAL）
           且工作区开启 Screening Agent 时，异步分发初筛评估任务（不阻塞业务请求）。
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from hr.models import Application, ApplicationStatus, HrConfig, RelationType


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
        dispatch_event_screening(instance.id)
    except Exception as exc:
        # 事件触发失败不影响业务请求；后续可人工触发
        import logging
        logging.getLogger("hr").warning("Screening dispatch failed for application %s: %s", instance.id, exc)
