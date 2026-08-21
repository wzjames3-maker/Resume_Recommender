# coding=utf-8
"""
    @project: MaxKB
    @Author：虎
    @file： lib.py
    @date：2024/8/16 17:12
    @desc: 兼容旧路径：请使用 celery.py，新代码应 from maxkb.settings.celery import *
           本文件仅为向后兼容保留，实际配置在 celery.py
"""
from .celery import *  # noqa: F401,F403
