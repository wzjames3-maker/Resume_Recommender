# coding=utf-8
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException
from hr.serializers.ai import AiService
from hr.views.permissions import hr_access_required, hr_admin_required

_MAX_QUERY_LENGTH = 2000
_MAX_DESCRIPTION_LENGTH = 4096


def _service(request, workspace_id):
    return AiService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        hr_role=getattr(request, "hr_role", None),
    )


class HrAIConfigAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def get(self, request, workspace_id):
        return result.success(_service(request, workspace_id).get_config())

    @hr_admin_required
    def put(self, request, workspace_id):
        return result.success(_service(request, workspace_id).save_config(request.data))


class HrSearchParseAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def post(self, request, workspace_id):
        query = request.data.get("query")
        if not isinstance(query, str) or not query.strip():
            raise AppApiException(400, "query is required")
        if len(query) > _MAX_QUERY_LENGTH:
            raise AppApiException(400, "query is too long")
        return result.success(_service(request, workspace_id).parse_search(query.strip()))


class HrSkillExtractAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def post(self, request, workspace_id):
        description = request.data.get("description")
        if not isinstance(description, str) or not description.strip():
            raise AppApiException(400, "description is required")
        if len(description) > _MAX_DESCRIPTION_LENGTH:
            raise AppApiException(400, "description is too long")
        return result.success(_service(request, workspace_id).extract_skills(description.strip()))
