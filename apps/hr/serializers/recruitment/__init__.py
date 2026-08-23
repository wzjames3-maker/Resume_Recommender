# coding=utf-8
"""
@file：hr/serializers/recruitment/__init__.py
@desc：招聘域服务 facade（兼容层）。

原单文件 serializers/recruitment.py（单一 RecruitmentService）已按领域拆分为本包：
base（公共基座/辅助）、candidate、job、resume、interview 五个子模块；
此处以多继承组合出 RecruitmentService，并保持旧导入路径 100% 兼容：
    from hr.serializers.recruitment import RecruitmentService
"""
import os  # noqa: F401  # 兼容保留：tests 以 patch("hr.serializers.recruitment.os.remove") 打桩，需本命名空间可解析到 os

# 兼容保留：tests 以 patch("hr.serializers.recruitment.parse_resume_task.delay") 打桩；
# mock 需在本模块命名空间解析到该任务对象（delay 打在共享 task 对象上，对 resume 子模块同样生效）。
from hr.task.resume import parse_resume_task  # noqa: F401

from .base import CANDIDATE_EXPORT_FIELDS, RecruitmentServiceBase, logger  # noqa: F401
from .candidate import CandidateMixin
from .interview import InterviewMixin, _INTERVIEW_STATUS_TRANSITIONS  # noqa: F401
from .job import JobMixin
from .resume import ResumeMixin


class RecruitmentService(CandidateMixin, JobMixin, ResumeMixin, InterviewMixin, RecruitmentServiceBase):
    """招聘域服务（facade）：由各领域 Mixin 组合而成，对外行为与拆分前的单类实现一致。"""
