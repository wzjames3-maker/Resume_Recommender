# coding=utf-8
"""
    @project: MaxKB
    @file： access.py
    @date：2026/8/14
    @desc: HR 授权管理与审计查询 API
"""
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from hr.serializers.access import AccessService, AuditLogService
from hr.views.permissions import hr_access_required, hr_admin_required


class HrAccessAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def get(self, request, workspace_id):
        return result.success(AccessService(workspace_id, request.user.id).list_access())

    @hr_admin_required
    def put(self, request, workspace_id):
        items = request.data.get("items")
        return result.success(AccessService(workspace_id, request.user.id).set_access(items))


class HrAccessMeAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id):
        return result.success({"role": request.hr_role})


class HrAuditLogAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def get(self, request, workspace_id):
        query = request.query_params
        current_page = AuditLogService._page(query, "current_page")
        page_size = AuditLogService._page(query, "page_size")
        return result.success(AuditLogService(workspace_id).page_audit_logs(current_page, page_size, query))
