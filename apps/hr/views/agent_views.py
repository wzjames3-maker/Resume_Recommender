# coding=utf-8
"""
    @project: MaxKB
    @file： agent_views.py
    @date：2026/8/17
    @desc: D1 Screening Agent API：人工触发运行 / Proposal 审批（accept/dismiss）/ 列表
"""
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException, NotFound404
from hr.agents.proposals import ProposalService
from hr.agents.runner import run_screening_agent
from hr.models import HrAgentTriggerType
from hr.views.permissions import hr_access_required, hr_operator_required

_AGENT_TYPES = ("SCREENING",)


class AgentRunAPI(APIView):
    """人工触发 Agent 运行：POST /hr/agents/{agent_type}/run，OPERATOR+。"""

    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id, agent_type):
        if agent_type not in _AGENT_TYPES:
            raise AppApiException(400, "agent_type must be one of " + "|".join(_AGENT_TYPES))
        application_id = request.data.get("application_id")
        if not application_id:
            raise AppApiException(400, "application_id is required")
        output = run_screening_agent(
            application_id,
            trigger_type=HrAgentTriggerType.MANUAL,
            user_id=request.user.id,
        )
        if output is None:
            raise NotFound404(404, "Resource not found")
        return result.success(output)


class ProposalListAPI(APIView):
    """按 Application 列出提案（含惰性 EXPIRED）。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def get(self, request, workspace_id, application_id):
        service = ProposalService(
            workspace_id=workspace_id,
            user_id=request.user.id,
            hr_role=getattr(request, "hr_role", None),
        )
        return result.success(service.list_for_application(application_id))


class ProposalAcceptAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id, proposal_id):
        service = ProposalService(
            workspace_id=workspace_id,
            user_id=request.user.id,
            hr_role=getattr(request, "hr_role", None),
        )
        return result.success(service.accept(proposal_id, request.data))


class ProposalDismissAPI(APIView):
    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id, proposal_id):
        service = ProposalService(
            workspace_id=workspace_id,
            user_id=request.user.id,
            hr_role=getattr(request, "hr_role", None),
        )
        return result.success(service.dismiss(proposal_id, request.data))
