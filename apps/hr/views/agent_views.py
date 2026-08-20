# coding=utf-8
"""
    @project: MaxKB
    @file： agent_views.py
    @date：2026/8/17
    @desc: Agent API（D1-D3）：人工触发运行（SCREENING/JD_DRAFT/INTERVIEW_COPILOT/
           SOURCING/COMMUNICATION_DRAFT）/ Proposal 审批（accept/dismiss）/
           按目标列表（application/job/interview）/ 反馈闭环统计
"""
import uuid as _uuid

from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.agents.copilot_runner import run_interview_copilot
from hr.agents.draft_runner import run_communication_draft
from hr.agents.jd_runner import run_jd_draft_agent
from hr.agents.proposals import ProposalService
from hr.agents.runner import run_screening_agent
from hr.agents.sourcing_runner import run_sourcing_agent
from hr.agents.scope import validate_resume_database_ids
from hr.models import HrAgentTriggerType
from hr.services.agent_stats import agent_feedback_stats
from hr.services.agent_workbench import get_evidence_paragraph, get_run, list_proposals, list_runs, retry_run
from hr.views.permissions import hr_access_required, hr_operator_required


def _require_uuid(value, field_name="id"):
    try:
        _uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise AppApiException(400, f"{field_name} is invalid") from exc


_AGENT_TYPES = ("SCREENING", "JD_DRAFT", "INTERVIEW_COPILOT", "SOURCING", "COMMUNICATION_DRAFT")
_OPERATOR_AGENT_TYPES = ("SCREENING", "JD_DRAFT", "SOURCING", "COMMUNICATION_DRAFT")


def _proposal_service(request, workspace_id):
    return ProposalService(
        workspace_id=workspace_id,
        user_id=request.user.id,
        hr_role=getattr(request, "hr_role", None),
    )


class AgentRunAPI(APIView):
    """人工触发 Agent 运行：POST /hr/agents/{agent_type}/run。
    SCREENING/JD_DRAFT/SOURCING/COMMUNICATION_DRAFT 要求 OPERATOR+；
    INTERVIEW_COPILOT 允许本人面试官（VIEWER 只见脱敏数据）。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def post(self, request, workspace_id, agent_type):
        if agent_type not in _AGENT_TYPES:
            raise AppApiException(400, "agent_type must be one of " + "|".join(_AGENT_TYPES))
        hr_role = getattr(request, "hr_role", None)
        resume_database_ids = request.data.getlist("resume_database_ids") if hasattr(request.data, "getlist") else None
        if not resume_database_ids:
            resume_database_ids = request.data.get("resume_database_ids") or request.data.get("resume_database_id")
        resume_database_ids = validate_resume_database_ids(workspace_id, resume_database_ids)
        if agent_type in _OPERATOR_AGENT_TYPES and hr_role not in ("OPERATOR", "ADMIN"):
            raise AppUnauthorizedFailed(403, "Operator permission is required")
        if agent_type in ("SCREENING", "COMMUNICATION_DRAFT"):
            application_id = request.data.get("application_id")
            if not application_id:
                raise AppApiException(400, "application_id is required")
            _require_uuid(application_id, "application_id")
            if agent_type == "SCREENING":
                output = run_screening_agent(
                    application_id,
                    trigger_type=HrAgentTriggerType.MANUAL,
                    user_id=request.user.id,
                    workspace_id=workspace_id,
                    resume_database_ids=resume_database_ids,
                )
            else:
                output = run_communication_draft(
                    application_id,
                    data=request.data,
                    user_id=request.user.id,
                    hr_role=hr_role,
                    workspace_id=workspace_id,
                )
        elif agent_type in ("JD_DRAFT", "SOURCING"):
            job_id = request.data.get("job_id")
            if not job_id:
                raise AppApiException(400, "job_id is required")
            _require_uuid(job_id, "job_id")
            if agent_type == "JD_DRAFT":
                output = run_jd_draft_agent(
                    job_id, trigger_type=HrAgentTriggerType.MANUAL, user_id=request.user.id,
                    workspace_id=workspace_id,
                )
            else:
                output = run_sourcing_agent(
                    job_id, trigger_type=HrAgentTriggerType.MANUAL, user_id=request.user.id,
                    workspace_id=workspace_id,
                    data={"resume_database_ids": resume_database_ids},
                )
        else:
            interview_id = request.data.get("interview_id")
            if not interview_id:
                raise AppApiException(400, "interview_id is required")
            _require_uuid(interview_id, "interview_id")
            output = run_interview_copilot(
                interview_id,
                data=request.data,
                user_id=request.user.id,
                hr_role=hr_role,
                workspace_id=workspace_id,
            )
        if output is None:
            raise NotFound404(404, "Resource not found")
        return result.success(output)


class AgentStatsAPI(APIView):
    """反馈闭环统计：GET /hr/agents/stats（OPERATOR+，采纳率供 dashboard 与阈值标定）。"""

    authentication_classes = [TokenAuth]

    @hr_operator_required
    def get(self, request, workspace_id):
        return result.success(agent_feedback_stats(workspace_id))


class AgentRunListAPI(APIView):
    """Agent 工作台运行列表：只读运行账本和筛选结果。"""

    authentication_classes = [TokenAuth]

    @hr_operator_required
    def get(self, request, workspace_id):
        return result.success(list_runs(workspace_id, request.query_params))


class AgentRunDetailAPI(APIView):
    """Agent 工作台运行详情：工具轨迹、输出、证据和关联提案。"""

    authentication_classes = [TokenAuth]

    @hr_operator_required
    def get(self, request, workspace_id, run_id):
        return result.success(get_run(workspace_id, run_id))


class AgentEvidenceParagraphAPI(APIView):
    """按 workspace 读取工作台证据对应的简历原文段落。"""

    authentication_classes = [TokenAuth]

    @hr_operator_required
    def get(self, request, workspace_id, paragraph_id):
        return result.success(get_evidence_paragraph(workspace_id, paragraph_id))


class AgentRunRetryAPI(APIView):
    """失败/跳过运行的受控重试；不会覆盖原运行记录。"""

    authentication_classes = [TokenAuth]

    @hr_operator_required
    def post(self, request, workspace_id, run_id):
        return result.success(retry_run(workspace_id, run_id, request.user.id, request.data))


class AgentProposalInboxAPI(APIView):
    """跨 Application/Job/Interview 的 Proposal 收件箱。"""

    authentication_classes = [TokenAuth]

    @hr_operator_required
    def get(self, request, workspace_id):
        return result.success(list_proposals(workspace_id, request.query_params))


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
