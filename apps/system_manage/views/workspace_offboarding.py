# coding=utf-8
"""
    @project: MaxKB
    @file： workspace_offboarding.py
    @date：2026/8/18
    @desc：内核 Workspace 注销 / 数据返还 Web API。
"""
from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException
from rest_framework.views import APIView

from system_manage.services.workspace_offboarding import (
    WorkspaceOffboardingService,
    export_workspace_data,
    offboard_workspace,
    preview_workspace_offboarding,
)
from users.serializers.user import is_workspace_manage


def _require_workspace_manager(request, workspace_id):
    if not is_workspace_manage(str(request.user.id), workspace_id):
        return result.Result(code=403, message="Workspace administrator permission is required", response_status=403)


class WorkspaceOffboardingPreviewAPI(APIView):
    authentication_classes = [TokenAuth]

    def get(self, request, workspace_id):
        permission_error = _require_workspace_manager(request, workspace_id)
        if permission_error:
            return permission_error
        return result.success(preview_workspace_offboarding(workspace_id))


class WorkspaceOffboardingExportAPI(APIView):
    authentication_classes = [TokenAuth]

    def get(self, request, workspace_id):
        permission_error = _require_workspace_manager(request, workspace_id)
        if permission_error:
            return permission_error
        return result.success(export_workspace_data(workspace_id))


class WorkspaceOffboardingStorageAPI(APIView):
    authentication_classes = [TokenAuth]

    def get(self, request, workspace_id):
        permission_error = _require_workspace_manager(request, workspace_id)
        if permission_error:
            return permission_error
        return result.success(WorkspaceOffboardingService.storage_cleanup_status(workspace_id))

    def post(self, request, workspace_id):
        permission_error = _require_workspace_manager(request, workspace_id)
        if permission_error:
            return permission_error
        return result.success(WorkspaceOffboardingService.retry_storage_cleanup(workspace_id))


class WorkspaceOffboardingAPI(APIView):
    authentication_classes = [TokenAuth]

    def post(self, request, workspace_id):
        permission_error = _require_workspace_manager(request, workspace_id)
        if permission_error:
            return permission_error
        if request.data.get("confirm_workspace_id") != workspace_id:
            raise AppApiException(400, "confirm_workspace_id must match workspace_id")
        return result.success(
            offboard_workspace(
                workspace_id,
                user_id=request.user.id,
                force=request.data.get("force") is True,
                include_export=request.data.get("export") is True,
            )
        )
