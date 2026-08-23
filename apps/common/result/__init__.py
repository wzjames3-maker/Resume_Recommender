# coding=utf-8
"""
    @project: MaxKB
    @Author：虎虎
    @file： __init__.py
    @date：2025/4/14 15:45
    @desc:
"""
from .api import DefaultResultSerializer, ResultSerializer, PageDataResponse, ResultPageSerializer
from .result import Page, Result, success, error

__all__ = [
    'DefaultResultSerializer',
    'ResultSerializer',
    'PageDataResponse',
    'ResultPageSerializer',
    'Page',
    'Result',
    'success',
    'error',
]
