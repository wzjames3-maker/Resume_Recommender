from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.auth.authentication import has_permissions
from common.constants.permission_constants import RoleConstants
from hr.serializers.recruitment import RecruitmentService
from users.serializers.user import is_workspace_manage


def _service(request, workspace_id):
    return RecruitmentService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        is_workspace_manage=is_workspace_manage(request.user.id, workspace_id),
    )


member_required = has_permissions(
    RoleConstants.USER.get_workspace_role(),
    RoleConstants.WORKSPACE_MANAGE.get_workspace_role(),
)
manage_required = has_permissions(RoleConstants.WORKSPACE_MANAGE.get_workspace_role())


class CandidateAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def post(self, request, workspace_id):
        return result.success(_service(request, workspace_id).create_candidate(request.data))

    class Page(APIView):
        authentication_classes = [TokenAuth]

        @member_required
        def get(self, request, workspace_id, current_page, page_size):
            return result.success(
                _service(request, workspace_id).page_candidates(current_page, page_size, request.query_params)
            )


class CandidateDetailAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def get(self, request, workspace_id, candidate_id):
        return result.success(_service(request, workspace_id).get_candidate(candidate_id))

    @manage_required
    def put(self, request, workspace_id, candidate_id):
        return result.success(_service(request, workspace_id).edit_candidate(candidate_id, request.data))

    class Archive(APIView):
        authentication_classes = [TokenAuth]

        @manage_required
        def put(self, request, workspace_id, candidate_id):
            return result.success(_service(request, workspace_id).archive_candidate(candidate_id))


class JobAPI(APIView):
    authentication_classes = [TokenAuth]

    @manage_required
    def post(self, request, workspace_id):
        return result.success(_service(request, workspace_id).create_job(request.data))

    class Page(APIView):
        authentication_classes = [TokenAuth]

        @member_required
        def get(self, request, workspace_id, current_page, page_size):
            return result.success(_service(request, workspace_id).page_jobs(current_page, page_size, request.query_params))

    class Assignment(APIView):
        authentication_classes = [TokenAuth]

        @member_required
        def post(self, request, workspace_id, job_id):
            return result.success(
                _service(request, workspace_id).create_assignment(job_id, request.data.get("candidate_id"), request.data)
            )


class JobDetailAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def get(self, request, workspace_id, job_id):
        return result.success(_service(request, workspace_id).get_job(job_id))

    @manage_required
    def put(self, request, workspace_id, job_id):
        return result.success(_service(request, workspace_id).edit_job(job_id, request.data))


class AssignmentAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def put(self, request, workspace_id, assignment_id):
        return result.success(_service(request, workspace_id).update_assignment(assignment_id, request.data))
