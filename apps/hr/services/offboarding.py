# coding=utf-8
"""
    @project: MaxKB
    @file： offboarding.py
    @date：2026/8/18
    @desc：HR 工作区注销编排回调：供内核 workspace 生命周期与 HR Web API 共同调用。
           本精简内核没有统一 Workspace ORM/注销编排，因此这里提供稳定的 HR callback contract；
           内核或上层租户服务在删除其它域数据前调用 preview/export，再调用 offboard_workspace。
"""
from common.exception.app_exception import AppApiException
from hr.management.commands.hr_offboard_workspace import Command
from hr.models import HrOffboard


def preview_workspace_offboarding(workspace_id):
    """返回逐表计数和活跃守卫，不修改数据库。"""
    return Command().execute_offboarding(workspace_id, dry_run=True)


def export_workspace_data(workspace_id):
    """返回脱敏的数据返还包，不修改数据库；已注销工作区不可再次导出。"""
    if HrOffboard.objects.filter(workspace_id=workspace_id).exists():
        raise AppApiException(409, "workspace is already offboarded")
    return Command()._build_export(workspace_id)


def offboard_workspace(workspace_id, *, user_id, force=False, include_export=False, delete_storage=True):
    """执行 HR 域注销，作为内核 workspace 注销编排的幂等回调。

    user_id 必须由上层认证主体或系统注销任务显式传入；阻塞时返回 HTTP/业务 409，
    其余结果包含 status、counts、tombstone 时间和可选 data-return export。
    """
    result = Command().execute_offboarding(
        workspace_id,
        user_id=user_id,
        force=force,
        include_export=include_export,
        delete_storage=delete_storage,
    )
    if result["status"] == "BLOCKED":
        issues = "；".join(result.get("active_issues") or [])
        raise AppApiException(409, f"workspace offboarding blocked: {issues}")
    return result
