import os
import tempfile

import uuid_utils.compat as uuid
from rest_framework.parsers import MultiPartParser
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


class ResumeAPI(APIView):
    authentication_classes = [TokenAuth]
    parser_classes = [MultiPartParser]

    @member_required
    def post(self, request, workspace_id):
        source_channel = request.data.get("source_channel", "OTHER")
        files = []
        for upload in request.FILES.getlist("files"):
            temp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid7()}_{upload.name}")
            with open(temp_path, "wb") as handle:
                for chunk in upload.chunks():
                    handle.write(chunk)
            extension = os.path.splitext(upload.name)[1].lstrip(".").lower()
            files.append((temp_path, upload.name, extension))
        return result.success(_service(request, workspace_id).upload_resumes(files, source_channel))


class ResumeListAPI(APIView):
    authentication_classes = [TokenAuth]

    @member_required
    def get(self, request, workspace_id, candidate_id):
        return result.success(_service(request, workspace_id).list_candidate_resumes(candidate_id))


class ResumeDetailAPI(APIView):
    authentication_classes = [TokenAuth]

    @manage_required
    def delete(self, request, workspace_id, resume_id):
        return result.success(_service(request, workspace_id).delete_resume(resume_id))
