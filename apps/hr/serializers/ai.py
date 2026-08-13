# coding=utf-8
from common.exception.app_exception import AppApiException, AppUnauthorizedFailed
from hr.models import HrConfig
from hr.services.ai_parser import extract_skills as _extract_skills
from hr.services.ai_parser import parse_search_conditions as _parse_search_conditions
from models_provider.tools import get_model_by_id, get_model_instance_by_model_workspace_id

_MODEL_TYPE_LLM = "LLM"


class AiService:
    def __init__(self, workspace_id, user_id, is_workspace_manage):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.is_workspace_manage = is_workspace_manage

    def _require_manage(self):
        if not self.is_workspace_manage:
            raise AppUnauthorizedFailed(401, "Permission denied")

    def get_config(self):
        config = HrConfig.objects.filter(workspace_id=self.workspace_id).first()
        return {"llm_model_id": config.llm_model_id if config else None}

    def save_config(self, data):
        self._require_manage()
        model_id = data.get("llm_model_id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise AppApiException(400, "llm_model_id is required")
        model_id = model_id.strip()
        try:
            model = get_model_by_id(model_id, self.workspace_id)
        except Exception as exc:
            raise AppApiException(400, "模型不存在或不可用") from exc
        if model.model_type != _MODEL_TYPE_LLM:
            raise AppApiException(400, "请选择 LLM 类型模型")
        config, _ = HrConfig.objects.update_or_create(
            workspace_id=self.workspace_id, defaults={"llm_model_id": model_id}
        )
        return {"llm_model_id": config.llm_model_id}

    def _model(self):
        config = HrConfig.objects.filter(workspace_id=self.workspace_id).first()
        if config is None:
            raise AppApiException(400, "请先在 AI 设置中选择模型")
        try:
            model = get_model_by_id(config.llm_model_id, self.workspace_id)
        except Exception as exc:
            raise AppApiException(400, "请先在 AI 设置中选择模型") from exc
        if model.model_type != _MODEL_TYPE_LLM:
            raise AppApiException(400, "请选择 LLM 类型模型")
        try:
            return get_model_instance_by_model_workspace_id(config.llm_model_id, self.workspace_id)
        except Exception as exc:
            raise AppApiException(400, "请先在 AI 设置中选择模型") from exc

    def parse_search(self, query):
        if not isinstance(query, str) or not query.strip():
            raise AppApiException(400, "query is required")
        if len(query) > 2000:
            raise AppApiException(400, "query is too long")
        return {"conditions": _parse_search_conditions(self._model(), query.strip())}

    def extract_skills(self, description):
        if not isinstance(description, str) or not description.strip():
            raise AppApiException(400, "description is required")
        if len(description) > 4096:
            raise AppApiException(400, "description is too long")
        return {"skills": _extract_skills(self._model(), description.strip())}
