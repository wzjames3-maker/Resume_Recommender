# coding=utf-8
"""
    @project: MaxKB
    @file： import_views.py
    @date：2026/8/15
    @desc: B4 候选人 CSV 批量导入与模板下载 API
"""
import csv
import io

from django.http import HttpResponse
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException
from hr.serializers.import_service import ImportService
from hr.views.permissions import hr_access_required, hr_admin_required


def _import_service(request, workspace_id):
    return ImportService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        hr_role=getattr(request, "hr_role", None),
    )


class CandidateImportAPI(APIView):
    authentication_classes = [TokenAuth]
    parser_classes = [MultiPartParser]

    @hr_admin_required
    def post(self, request, workspace_id):
        upload = request.FILES.get("file")
        if upload is None:
            raise AppApiException(400, "file is required")
        if upload.size > 2 * 1024 * 1024:
            raise AppApiException(400, "File exceeds 2 MB limit")
        try:
            content = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AppApiException(400, "CSV must be UTF-8 encoded") from exc
        return result.success(_import_service(request, workspace_id).import_candidates_csv(content))


class CandidateImportTemplateAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id):
        headers, sample = _import_service(request, workspace_id).import_template()
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerow(sample)
        http_response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
        http_response["Content-Disposition"] = 'attachment; filename="candidates_import_template.csv"'
        return http_response
