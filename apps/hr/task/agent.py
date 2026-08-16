# coding=utf-8
"""
    @project: MaxKB
    @file： agent.py
    @date：2026/8/17
    @desc: Screening Agent Celery 任务（celery-once 防重，key=application_id）。
"""
from celery_once import QueueOnce

from hr.agents.runner import run_screening_agent
from ops import celery_app


@celery_app.task(base=QueueOnce, once={"keys": ["application_id"]}, name="celery:hr_run_screening_agent")
def run_screening_agent_task(application_id):
    """事件触发的初筛评估；防重：同一 Application 不会并发排队多个任务。"""
    run_screening_agent(application_id, trigger_type="EVENT", user_id=None)
