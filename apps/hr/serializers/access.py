# coding=utf-8
"""
    @project: MaxKB
    @file： access.py
    @date：2026/8/14
    @desc: HR 授权管理与审计查询服务
"""
from datetime import datetime

import uuid_utils.compat as uuid

from common.exception.app_exception import AppApiException
from hr.models import HrAccess, HrAuditAction, HrAuditLog, HrAuditObjectType, HrRole
from hr.services.audit import write_audit_log
from users.models import User
from users.serializers.user import UserManageSerializer


class AccessService:
    def __init__(self, workspace_id, user_id):
        self.workspace_id = workspace_id
        self.user_id = user_id

    def list_access(self):
        role_map = {
            access.user_id: access.role
            for access in HrAccess.objects.filter(workspace_id=self.workspace_id)
        }
        members = []
        for member in UserManageSerializer().get_user_members(self.workspace_id):
            user_id = member["id"]
            members.append({**member, "hr_role": role_map.get(user_id)})
        return members

    @staticmethod
    def _item_user_id(item):
        if not isinstance(item, dict):
            raise AppApiException(400, "items must be a list of objects")
        value = item.get("user_id")
        if not isinstance(value, str) or not value.strip():
            raise AppApiException(400, "user_id is required")
        try:
            return uuid.UUID(value)
        except (ValueError, TypeError) as exc:
            raise AppApiException(400, "user_id is invalid") from exc

    def set_access(self, items):
        if not isinstance(items, list):
            raise AppApiException(400, "items must be a list")
        member_ids = {
            member["id"] for member in UserManageSerializer().get_user_members(self.workspace_id)
        }
        normalized = []
        for item in items:
            user_id = self._item_user_id(item)
            role = item.get("role")
            if role is not None and role not in HrRole.values:
                raise AppApiException(400, "role is invalid")
            if user_id not in member_ids:
                raise AppApiException(400, "User is not a workspace member")
            normalized.append((user_id, role))
        for user_id, role in normalized:
            if role is None:
                HrAccess.objects.filter(workspace_id=self.workspace_id, user_id=user_id).delete()
                write_audit_log(self.workspace_id, self.user_id, "REVOKE_ACCESS", "HR_ACCESS", user_id)
            else:
                HrAccess.objects.update_or_create(
                    workspace_id=self.workspace_id, user_id=user_id, defaults={"role": role}
                )
                write_audit_log(self.workspace_id, self.user_id, "GRANT_ACCESS", "HR_ACCESS", user_id, detail=role)
        return self.list_access()


class AuditLogService:
    def __init__(self, workspace_id):
        self.workspace_id = workspace_id

    @staticmethod
    def _page(query, name):
        try:
            return max(int(query.get(name, "1")), 1)
        except (TypeError, ValueError) as exc:
            raise AppApiException(400, f"{name} is invalid") from exc

    @staticmethod
    def _time(value, name):
        if value in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise AppApiException(400, f"{name} is invalid") from exc

    def page_audit_logs(self, current_page, page_size, query):
        queryset = HrAuditLog.objects.filter(workspace_id=self.workspace_id)
        user_id = query.get("user_id")
        if user_id:
            try:
                user_id = uuid.UUID(str(user_id))
            except (ValueError, TypeError) as exc:
                raise AppApiException(400, "user_id is invalid") from exc
            queryset = queryset.filter(user_id=user_id)
        action = query.get("action")
        if action:
            if action not in HrAuditAction.values:
                raise AppApiException(400, "action is invalid")
            queryset = queryset.filter(action=action)
        object_type = query.get("object_type")
        if object_type:
            if object_type not in HrAuditObjectType.values:
                raise AppApiException(400, "object_type is invalid")
            queryset = queryset.filter(object_type=object_type)
        start_time = self._time(query.get("start_time"), "start_time")
        if start_time:
            queryset = queryset.filter(create_time__gte=start_time)
        end_time = self._time(query.get("end_time"), "end_time")
        if end_time:
            queryset = queryset.filter(create_time__lte=end_time)
        total = queryset.count()
        start = (current_page - 1) * page_size
        logs = queryset.order_by("-create_time")[start:start + page_size]
        name_map = {
            user.id: user.nick_name
            for user in User.objects.filter(id__in=[log.user_id for log in logs])
        }
        return {
            "total": total,
            "records": [
                {
                    "id": str(log.id),
                    "user_id": str(log.user_id),
                    "nick_name": name_map.get(log.user_id),
                    "action": log.action,
                    "object_type": log.object_type,
                    "object_id": log.object_id,
                    "result": log.result,
                    "detail": log.detail,
                    "create_time": log.create_time,
                }
                for log in logs
            ],
        }
