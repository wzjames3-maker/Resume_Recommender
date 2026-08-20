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
from hr.serializers.access import AccessService, AuditLogService, hr_members
from hr.views.permissions import hr_access_required, hr_admin_required


class HrMembersAPI(APIView):
    """HR 成员目录（任意 HR 成员可读）：负责人/面试官下拉与展示用。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id):
        return result.success(hr_members(workspace_id))


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
        page_size = min(AuditLogService._page(query, "page_size"), 100)
        return result.success(AuditLogService(workspace_id).page_audit_logs(current_page, page_size, query))
