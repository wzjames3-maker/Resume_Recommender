# coding=utf-8
"""
    @project: MaxKB
    @Author：虎虎
    @file： __init__.py.py
    @date：2025/5/29 16:08
    @desc:
"""
from .chat_embed import ChatEmbedView
from .chat import (
    stream_image,
    ResourceProxy,
    OpenAIView,
    AnonymousAuthentication,
    ApplicationProfile,
    AuthProfile,
    ChatView,
    OpenView,
    CaptchaView,
    UploadFile,
)
from .chat_record import VoteView, HistoricalConversationView, HistoricalConversationRecordView, ChatRecordView

__all__ = [
    'ChatEmbedView',
    'stream_image',
    'ResourceProxy',
    'OpenAIView',
    'AnonymousAuthentication',
    'ApplicationProfile',
    'AuthProfile',
    'ChatView',
    'OpenView',
    'CaptchaView',
    'UploadFile',
    'VoteView',
    'HistoricalConversationView',
    'HistoricalConversationRecordView',
    'ChatRecordView',
]
