# coding=utf-8
"""
    @project: MaxKB
    @Author：虎虎
    @file： __init__.py
    @date：2025/5/9 18:51
    @desc:
"""
from .application_api_key import get_application_operation_object, ApplicationKey
from .application import get_application_operation_object, get_application_operation_object_batch, ApplicationAPI
from .application_version import ApplicationVersionView
from .application_access_token import get_application_operation_object, AccessToken
from .application_stats import ApplicationStats
from .application_chat import get_application_operation_object, ApplicationChat, OpenView, ChatView, PromptGenerateView
from .application_chat_record import (
    ApplicationChatRecord,
    ApplicationChatRecordOperateAPI,
    ApplicationChatRecordAddKnowledge,
    ApplicationChatRecordImprove,
    ApplicationChatRecordImproveParagraph,
)
from .application_chat_link import ChatRecordLinkView, ChatRecordDetailView

__all__ = [
    'get_application_operation_object',
    'ApplicationKey',
    'get_application_operation_object_batch',
    'ApplicationAPI',
    'ApplicationVersionView',
    'AccessToken',
    'ApplicationStats',
    'ApplicationChat',
    'OpenView',
    'ChatView',
    'PromptGenerateView',
    'ApplicationChatRecord',
    'ApplicationChatRecordOperateAPI',
    'ApplicationChatRecordAddKnowledge',
    'ApplicationChatRecordImprove',
    'ApplicationChatRecordImproveParagraph',
    'ChatRecordLinkView',
    'ChatRecordDetailView',
]
