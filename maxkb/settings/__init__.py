# coding=utf-8
"""
    @project: MaxKB - 标准布局聚合入口
    @file： __init__.py
    @desc: 聚合 base/auth/logging/celery/mem，兼容旧 .lib 导入
"""
from .base import *  # noqa: F401,F403
from .logging import *  # noqa: F401,F403
from .auth import *  # noqa: F401,F403
try:
    from .celery import *  # noqa: F401,F403 - 标准命名
except ImportError:
    from .lib import *  # noqa: F401,F403 - 兼容旧路径
from .mem import *  # noqa: F401,F403

# 兼容旧文件 lib.py 继续可用
try:
    import sys as _sys
    from . import celery as _celery
    _sys.modules[__name__ + ".lib"] = _celery
except Exception:
    pass