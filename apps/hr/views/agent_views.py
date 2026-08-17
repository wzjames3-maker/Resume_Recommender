# coding=utf-8
"""
    @project: MaxKB
    @file： agent_views.py
    @date：2026/8/17
    @desc: Agent API（D1/D2）：人工触发运行（SCREENING/JD_DRAFT/INTERVIEW_COPILOT）/
           Proposal 审批（accept/dismiss）/ 按目标列表（application/job/interview）
"""
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.agents.copilot_runner import run_interview_copilot
from hr.agents.jd_runner import run_jd_draft_agent
from hr.agents.proposals import ProposalService
from hr.agents.runner import run_screening_agent
from hr.models import HrAgentTriggerType
from hr.views.permissions import hr_access_required, hr_operator_required

_AGENT_TYPES = ("SCREENING", "JD_DRAFT", "INTERVIEW_COPILOT")
_OPERATOR_AGENT_TYPES = ("SCREENING", "JD_DRAFT")


def _proposal_service(request, workspace_id):
    return ProposalService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        hr_role=getattr(request, "hr_role", None),
    )


class AgentRunAPI(APIView):
    """人工触发 Agent 运行：POST /hr/agents/{agent_type}/run。
    SCREENING/JD_DRAFT 要求 OPERATOR+；INTERVIEW_COPILOT 允许本人面试官（VIEWER 只见脱敏数据）。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def post(self, request, workspace_id, agent_type):
        if agent_type not in _AGENT_TYPES:
            raise AppApiException(400, "agent_type must be one of " + "|".join(_AGENT_TYPES))
        hr_role = getattr(request, "hr_role", None)
        if agent_type in _OPERATOR_AGENT_TYPES and hr_role not in ("OPERATOR", "ADMIN"):
            raise AppUnauthorizedFailed(403, "Operator permission is required")
        if agent_type == "SCREENING":
            application_id = request.data.get("application_id")
            if not application_id:
                raise AppApiException(400, "application_id is required")
            output = run_screening_agent(
                application_id,
                trigger_type=HrAgentTriggerType.MANUAL,
                user_id=request.user.id,
            )
        elif agent_type == "JD_DRAFT":
            job_id = request.data.get("job_id")
            if not job_id:
                raise AppApiException(400, "job_id is required")
            output = run_jd_draft_agent(job_id, trigger_type=HrAgentTriggerType.MANUAL, user_id=request.user.id)
        else:
            interview_id = request.data.get("interview_id")
            if not interview_id:
                raise AppApiException(400, "interview_id is required")
            output = run_interview_copilot(
                interview_id,
                data=request.data,
                user_id=request.user.id,
                hr_role=hr_role,
            )
        if output is None:
            raise NotFound404(404, "Resource not found")
        return result.success(output)


class ProposalListAPI(APIView):
    """按 Application 列出提案（含惰性 EXPIRED）。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, application_id):
        return result.success(_proposal_service(request, workspace_id).list_for_application(application_id))


class JobProposalListAPI(APIView):
    """按 Job 列出提案（JD 草稿）。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, job_id):
        return result.success(_proposal_service(request, workspace_id).list_for_job(job_id))


class InterviewProposalListAPI(APIView):
    """按 Interview 列出提案（面试助手产物）。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, interview_id):
        return result.success(_proposal_service(request, workspace_id).list_for_interview(interview_id))


class ProposalAcceptAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id, proposal_id):
        return result.success(_proposal_service(request, workspace_id).accept(proposal_id, request.data))


class ProposalDismissAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id, proposal_id):
        return result.success(_proposal_service(request, workspace_id).dismiss(proposal_id, request.data))
