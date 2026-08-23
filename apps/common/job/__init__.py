# coding=utf-8
"""
    @project: maxkb
    @Author：虎
    @file： __init__.py
    @date：2024/3/14 11:54
    @desc:
"""
from .clean_chat_job import clean_chat_log_job, clean_chat_log_job_lock, clean_method, run
from . import clean_chat_job
from .clean_debug_file_job import clean_debug_file, clean_debug_file_lock, run
from . import clean_debug_file_job
from .client_access_num_job import client_access_num_reset_job, client_access_num_reset_job_lock, run
from . import client_access_num_job


def run():
    # client_access_num_job.run()
    clean_chat_job.run()
    clean_debug_file_job.run()
    client_access_num_job.run()

__all__ = [
    'clean_chat_job',
    'clean_chat_log_job',
    'clean_chat_log_job_lock',
    'clean_method',
    'run',
    'clean_debug_file_job',
    'clean_debug_file',
    'clean_debug_file_lock',
    'client_access_num_job',
    'client_access_num_reset_job',
    'client_access_num_reset_job_lock',
]
