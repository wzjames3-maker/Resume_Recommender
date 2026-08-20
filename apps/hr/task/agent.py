# coding=utf-8
"""
    @project: MaxKB
    @file： agent.py
    @date：2026/8/17
    @desc: Screening Agent Celery 任务（celery-once 防重，key=application_id）。
"""
from celery_once import QueueOnce

from django.conf import settings

from hr.agents.runner import run_screening_agent
from ops import celery_app

try:
    from hr.agents.runner_pydantic import run_screening_agent as run_screening_agent_pydantic

    _PYDANTIC_AVAILABLE = True
except ImportError:
    _PYDANTIC_AVAILABLE = False


def _use_pydantic():
    return _PYDANTIC_AVAILABLE and getattr(settings, "USE_PYDANTIC_AI", False)


@celery_app.task(base=QueueOnce, once={"keys": ["application_id"]}, name="celery:hr_run_screening_agent")
def run_screening_agent_task(application_id):
    """事件触发的初筛评估；防重：同一 Application 不会并发排队多个任务。"""
    runner = run_screening_agent_pydantic if _use_pydantic() else run_screening_agent
    runner(application_id, trigger_type="EVENT", user_id=None)
