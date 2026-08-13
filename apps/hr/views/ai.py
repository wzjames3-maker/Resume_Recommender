# coding=utf-8
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.auth.authentication import has_permissions
from common.constants.permission_constants import RoleConstants
from common.exception.app_exception import AppApiException
from hr.serializers.ai import AiService
from users.serializers.user import is_workspace_manage

_MAX_QUERY_LENGTH = 2000
_MAX_DESCRIPTION_LENGTH = 4096


def _service(request, workspace_id):
    return AiService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        is_workspace_manage=is_workspace_manage(request.user.id, workspace_id),
    )


member_required = has_permissions(
    RoleConstants.USER.get_workspace_role(),
    RoleConstants.WORKSPACE_MANAGE.get_workspace_role(),
)
manage_required = has_permissions(RoleConstants.WORKSPACE_MANAGE.get_workspace_role())


class HrAIConfigAPI(APIView):
    authentication_classes = [TokenAuth]

    @manage_required
    def get(self, request, workspace_id):
        return result.success(_service(request, workspace_id).get_config())

    @manage_required
    def put(self, request, workspace_id):
        return result.success(_service(request, workspace_id).save_config(request.data))


class HrSearchParseAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def post(self, request, workspace_id):
        query = request.data.get("query")
        if not isinstance(query, str) or not query.strip():
            raise AppApiException(400, "query is required")
        if len(query) > _MAX_QUERY_LENGTH:
            raise AppApiException(400, "query is too long")
        return result.success(_service(request, workspace_id).parse_search(query.strip()))


class HrSkillExtractAPI(APIView):
    authentication_classes = [TokenAuth]

    @manage_required
    def post(self, request, workspace_id):
        description = request.data.get("description")
        if not isinstance(description, str) or not description.strip():
            raise AppApiException(400, "description is required")
        if len(description) > _MAX_DESCRIPTION_LENGTH:
            raise AppApiException(400, "description is too long")
        return result.success(_service(request, workspace_id).extract_skills(description.strip()))
