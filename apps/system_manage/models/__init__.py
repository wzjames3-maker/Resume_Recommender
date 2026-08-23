# coding=utf-8
"""
    @project: MaxKB
    @Author：虎虎
    @file： __init__.py.py
    @date：2025/4/16 18:23
    @desc:
"""
from .workspace_user_permission import AuthTargetType, WorkspaceUserResourcePermission
from .system_setting import SettingType, SystemSetting
from .log_management import Log
from .chat_user import (
    ChatUser,
    UserGroup,
    UserGroupRelation,
    ResourceType,
    ResourceChatUserAuthorize,
    ResourceChatUserGroupAuthorize,
)
from .workspace_offboard import StorageCleanupStatus, WorkspaceOffboard, WorkspaceOffboardStorageCleanup

__all__ = [
    'AuthTargetType',
    'WorkspaceUserResourcePermission',
    'SettingType',
    'SystemSetting',
    'Log',
    'ChatUser',
    'UserGroup',
    'UserGroupRelation',
    'ResourceType',
    'ResourceChatUserAuthorize',
    'ResourceChatUserGroupAuthorize',
    'StorageCleanupStatus',
    'WorkspaceOffboard',
    'WorkspaceOffboardStorageCleanup',
]
