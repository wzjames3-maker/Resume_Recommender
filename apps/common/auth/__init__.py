# coding=utf-8
"""
    @project: MaxKB
    @Author：虎虎
    @file： __init__.py.py
    @date：2025/4/14 10:44
    @desc:
"""
from .authenticate import (
    token_cache,
    AnonymousAuthentication,
    AnonymousAuthenticationScheme,
    new_instance_by_class_path,
    handles,
    chat_handles,
    all_handles,
    TokenDetails,
    TokenAuth,
    ChatTokenAuth,
    AllTokenAuth,
    WebhookAuth,
)

__all__ = [
    'token_cache',
    'AnonymousAuthentication',
    'AnonymousAuthenticationScheme',
    'new_instance_by_class_path',
    'handles',
    'chat_handles',
    'all_handles',
    'TokenDetails',
    'TokenAuth',
    'ChatTokenAuth',
    'AllTokenAuth',
    'WebhookAuth',
]
