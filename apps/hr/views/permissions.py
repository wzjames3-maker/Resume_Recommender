# coding=utf-8
"""
    @project: MaxKB
    @file： permissions.py
    @date：2026/8/14
    @desc: HR 模块权限装饰器：hr_access_required / hr_admin_required
"""
from common.exception.app_exception import AppUnauthorizedFailed
from hr.models import HrRole
from hr.services.audit import get_hr_role, write_audit_log


def _deny(request, workspace_id):
    write_audit_log(
        workspace_id, request.user.id, "ACCESS_DENIED", "OTHER",
        result="DENIED", detail=request.path,
    )


def _current_user_id(request):
    user = getattr(request, "user", None)
    if user is None or getattr(user, "id", None) is None:
        return None
    return user.id


def hr_access_required(func):
    """
    要求用户具备任意 HR 角色（VIEWER/OPERATOR/ADMIN）；未授权 403 并写 ACCESS_DENIED 审计。
    """

    def run(view, request, **kwargs):
        user_id = _current_user_id(request)
        if user_id is None:
            raise AppUnauthorizedFailed(401, "Authentication credentials were not provided")
        role = get_hr_role(kwargs.get("workspace_id"), user_id)
        if role is None:
            _deny(request, kwargs.get("workspace_id"))
            raise AppUnauthorizedFailed(403, "HR access is required")
        request.hr_role = role
        return func(view, request, **kwargs)

    return run


def hr_operator_required(func):
    """
    要求用户具备 HR OPERATOR 或 ADMIN 角色；否则 403 并写 ACCESS_DENIED 审计。
    用于可读敏感数据（简历全文/流转日志等）的接口，VIEWER 一律拒绝。
    """

    def run(view, request, **kwargs):
        user_id = _current_user_id(request)
        if user_id is None:
            raise AppUnauthorizedFailed(401, "Authentication credentials were not provided")
        role = get_hr_role(kwargs.get("workspace_id"), user_id)
        if role not in (HrRole.OPERATOR, HrRole.ADMIN):
            _deny(request, kwargs.get("workspace_id"))
            raise AppUnauthorizedFailed(403, "HR operator permission is required")
        request.hr_role = role
        return func(view, request, **kwargs)

    return run


def hr_admin_required(func):
    """
    要求用户具备 HR ADMIN 角色；否则 403 并写 ACCESS_DENIED 审计。
    """

    def run(view, request, **kwargs):
        user_id = _current_user_id(request)
        if user_id is None:
            raise AppUnauthorizedFailed(401, "Authentication credentials were not provided")
        role = get_hr_role(kwargs.get("workspace_id"), user_id)
        if role != HrRole.ADMIN:
            _deny(request, kwargs.get("workspace_id"))
            raise AppUnauthorizedFailed(403, "HR administrator permission is required")
        request.hr_role = role
        return func(view, request, **kwargs)

    return run
