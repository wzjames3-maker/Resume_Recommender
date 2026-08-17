# coding=utf-8
"""
    @project: MaxKB
    @file： offboarding.py
    @date：2026/8/18
    @desc：HR 租户注销 / 数据返还 Web API。
"""
from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException
from hr.services.offboarding import export_workspace_data, offboard_workspace, preview_workspace_offboarding
from hr.views.permissions import hr_admin_required
from rest_framework.views import APIView


class HrOffboardingPreviewAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def get(self, request, workspace_id):
        return result.success(preview_workspace_offboarding(workspace_id))


class HrOffboardingExportAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def get(self, request, workspace_id):
        return result.success(export_workspace_data(workspace_id))


class HrOffboardingAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def post(self, request, workspace_id):
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
