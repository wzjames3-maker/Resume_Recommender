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


class HrResumeSearchAPI(APIView):
    """简历语义检索（阶段 3：双路召回 + RRF + rerank + Skill-AND）。"""

    authentication_classes = [TokenAuth]

    @hr_access_required
    def post(self, request, workspace_id):
        from hr.services.resume_search import search_resumes

        query = request.data.get("query")
        top_k = request.data.get("top_k", 5)
        recall_k = request.data.get("recall_k")
        similarity = request.data.get("similarity", 0.2)
        mode = request.data.get("mode", "auto")
        try:
            top_k = int(top_k)
            recall_k = int(recall_k) if recall_k is not None else None
            similarity = float(similarity)
        except (TypeError, ValueError):
            raise AppApiException(400, "top_k/recall_k/similarity must be numbers")
        if not isinstance(mode, str) or mode not in ("auto", "hybrid", "dense", "phrase", "skills"):
            raise AppApiException(400, "mode must be one of auto|hybrid|dense|phrase|skills")
        return result.success(search_resumes(
            workspace_id,
            query,
            top_k=top_k,
            recall_k=recall_k,
            similarity=similarity,
            mode=mode,
            hr_role=getattr(request, "hr_role", None),
            user_id=request.user.id,
            llm_model=_service(request, workspace_id)._model_or_none(),
            rerank_model=_service(request, workspace_id)._rerank_model_or_none(),
        ))
