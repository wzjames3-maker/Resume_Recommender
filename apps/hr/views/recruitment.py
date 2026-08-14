import os
import tempfile

import uuid_utils.compat as uuid
from django.http import FileResponse
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException
from hr.serializers.recruitment import RecruitmentService
from hr.views.permissions import hr_access_required, hr_admin_required


def _service(request, workspace_id):
    return RecruitmentService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        hr_role=getattr(request, "hr_role", None),
    )


class CandidateAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def post(self, request, workspace_id):
        return result.success(_service(request, workspace_id).create_candidate(request.data))

    class Page(APIView):
        authentication_classes = [TokenAuth]

        @hr_access_required
        def get(self, request, workspace_id, current_page, page_size):
            return result.success(
                _service(request, workspace_id).page_candidates(current_page, page_size, request.query_params)
            )


class CandidateDetailAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, candidate_id):
        return result.success(_service(request, workspace_id).get_candidate(candidate_id))

    @hr_admin_required
    def put(self, request, workspace_id, candidate_id):
        return result.success(_service(request, workspace_id).edit_candidate(candidate_id, request.data))

    class Archive(APIView):
        authentication_classes = [TokenAuth]

        @hr_admin_required
        def put(self, request, workspace_id, candidate_id):
            return result.success(_service(request, workspace_id).archive_candidate(candidate_id))

    class Merge(APIView):
        authentication_classes = [TokenAuth]

        @hr_admin_required
        def post(self, request, workspace_id, candidate_id):
            return result.success(_service(request, workspace_id).merge_candidates(candidate_id, request.data))


class CandidateCheckDuplicateAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def post(self, request, workspace_id):
        return result.success(_service(request, workspace_id).check_duplicate(request.data))


class JobAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def post(self, request, workspace_id):
        return result.success(_service(request, workspace_id).create_job(request.data))

    class Page(APIView):
        authentication_classes = [TokenAuth]

        @hr_access_required
        def get(self, request, workspace_id, current_page, page_size):
            return result.success(_service(request, workspace_id).page_jobs(current_page, page_size, request.query_params))

    class Assignment(APIView):
        authentication_classes = [TokenAuth]

        @hr_access_required
        def post(self, request, workspace_id, job_id):
            return result.success(
                _service(request, workspace_id).create_assignment(job_id, request.data.get("candidate_id"), request.data)
            )


class JobDetailAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, job_id):
        return result.success(_service(request, workspace_id).get_job(job_id))

    @hr_admin_required
    def put(self, request, workspace_id, job_id):
        return result.success(_service(request, workspace_id).edit_job(job_id, request.data))

    class Close(APIView):
        authentication_classes = [TokenAuth]

        @hr_admin_required
        def put(self, request, workspace_id, job_id):
            return result.success(
                _service(request, workspace_id).close_job(job_id, request.data.get("close_reason"))
            )

    class Reopen(APIView):
        authentication_classes = [TokenAuth]

        @hr_admin_required
        def put(self, request, workspace_id, job_id):
            return result.success(_service(request, workspace_id).reopen_job(job_id))


class AssignmentAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def put(self, request, workspace_id, assignment_id):
        return result.success(_service(request, workspace_id).update_assignment(assignment_id, request.data))


class ResumeAPI(APIView):
    authentication_classes = [TokenAuth]
    parser_classes = [MultiPartParser]

    @hr_access_required
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

    @hr_access_required
    def get(self, request, workspace_id, candidate_id):
        return result.success(_service(request, workspace_id).list_candidate_resumes(candidate_id))


class ResumeDetailAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def delete(self, request, workspace_id, resume_id):
        return result.success(_service(request, workspace_id).delete_resume(resume_id))

    class Download(APIView):
        authentication_classes = [TokenAuth]

        @hr_access_required
        def get(self, request, workspace_id, resume_id):
            file_path, file_name, content_type = _service(request, workspace_id).download_resume(resume_id)
            try:
                handle = open(file_path, "rb")
            except OSError as exc:
                raise AppApiException(500, "文件读取失败") from exc
            return FileResponse(handle, content_type=content_type, as_attachment=True, filename=file_name)

    class Content(APIView):
        authentication_classes = [TokenAuth]

        @hr_access_required
        def get(self, request, workspace_id, resume_id):
            return result.success(_service(request, workspace_id).resume_content(resume_id))


class JobMatchAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, job_id, current_page, page_size):
        return result.success(
            _service(request, workspace_id).match_job_candidates(job_id, current_page, page_size)
        )


class InterviewAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def post(self, request, workspace_id, assignment_id):
        return result.success(_service(request, workspace_id).create_interview(assignment_id, request.data))

    @hr_access_required
    def get(self, request, workspace_id, assignment_id):
        return result.success(_service(request, workspace_id).list_interviews(assignment_id))


class InterviewDetailAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def put(self, request, workspace_id, interview_id):
        return result.success(_service(request, workspace_id).update_interview(interview_id, request.data))


class ResumeBatchStatusAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id):
        ids_param = request.query_params.get("ids", "")
        resume_ids = [item.strip() for item in ids_param.split(",") if item.strip()]
        if not resume_ids:
            raise AppApiException(400, "ids is required")
        if len(resume_ids) > 200:
            raise AppApiException(400, "too many ids")
        return result.success(_service(request, workspace_id).batch_resume_status(resume_ids))
