# coding=utf-8
"""
    @project: MaxKB
    @file： application_views.py
    @date：2026/8/17
    @desc: ATS v2 Application / JobStage 命令 API
"""
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException
from hr.models import Job, JobStage
from hr.services.application_service import ApplicationService
from hr.views.permissions import hr_access_required, hr_admin_required, hr_operator_required


def _service(request, workspace_id):
    return ApplicationService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        hr_role=getattr(request, "hr_role", None),
    )


class JobStageListAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, job_id):
        job = Job.objects.filter(id=job_id, workspace_id=workspace_id).first()
        if job is None:
            raise AppApiException(404, "Resource not found")
        stages = JobStage.objects.filter(workspace_id=workspace_id, job=job).order_by("order")
        return result.success([
            {
                "id": str(stage.id),
                "key": stage.key,
                "name": stage.name,
                "color": stage.color,
                "order": stage.order,
                "is_system": stage.is_system,
            }
            for stage in stages
        ])


class ApplicationListAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id):
        job_id = request.data.get("job_id")
        candidate_id = request.data.get("candidate_id")
        if not job_id or not candidate_id:
            raise AppApiException(400, "job_id and candidate_id are required")
        return result.success(_service(request, workspace_id).create_application(job_id, candidate_id, request.data))


class ApplicationPageAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, current_page, page_size):
        return result.success(_service(request, workspace_id).page_applications(current_page, page_size, request.query_params))


class ApplicationMoveStageAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id, application_id):
        to_stage_id = request.data.get("to_stage_id")
        if not to_stage_id:
            raise AppApiException(400, "to_stage_id is required")
        return result.success(_service(request, workspace_id).move_stage(application_id, to_stage_id, request.data))


class ApplicationTerminalAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id, application_id):
        action = request.data.get("action")
        service = _service(request, workspace_id)
        if action == "reject":
            return result.success(service.reject_application(application_id, request.data))
        if action == "withdraw":
            return result.success(service.withdraw_application(application_id, request.data))
        if action == "close":
            return result.success(service.close_application(application_id, request.data))
        raise AppApiException(400, "action must be reject|withdraw|close")


class ApplicationRestoreAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_admin_required
    def post(self, request, workspace_id, application_id):
        return result.success(_service(request, workspace_id).restore_application(application_id, request.data))


class ApplicationEventAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, application_id):
        return result.success(_service(request, workspace_id).list_events(application_id))


class JobClosePreviewAPI(APIView):
    """R2 关闭预览：返回职位 ACTIVE Application 清单（STRICT/BULK 决策依据）。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, job_id):
        return result.success(_service(request, workspace_id).close_preview(job_id))


class JobCloseAPI(APIView):
    """R2 两阶段关闭：GET 预览 / POST STRICT|BULK 关闭。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, job_id):
        return result.success(_service(request, workspace_id).close_preview(job_id))

    @hr_admin_required
    def post(self, request, workspace_id, job_id):
        return result.success(_service(request, workspace_id).close_job(job_id, request.data))

class ApplicationInterviewAPI(APIView):
    """R3 面试挂 Application：创建要求 ACTIVE 且 Stage 为 SCREEN/INTERVIEW。"""

    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id, application_id):
        return result.success(_service(request, workspace_id).create_interview(application_id, request.data))

    @hr_access_required
    def get(self, request, workspace_id, application_id):
        return result.success(_service(request, workspace_id).list_interviews(application_id))
