# coding=utf-8
"""
    @project: MaxKB
    @file： pydantic_base.py
    @date：2026/8/20
    @desc: Pydantic AI 基础设施（Prompt 1）：
           替换手写 _invoke_llm/_validate_facts/_repair_json，
           提供 HrDeps、get_pydantic_model、create_agent。
"""
import json
import uuid

from pydantic import BaseModel, Field

from hr.agents.base import guard_limits, record_prompt_version, write_skipped_run
from hr.models import HrConfig

try:
    # Pydantic AI >=2.0 使用 OpenAIChatModel，兼容旧 OpenAIModel 别名
    try:
        from pydantic_ai.models.openai import OpenAIModel  # type: ignore
    except ImportError:
        from pydantic_ai.models.openai import OpenAIChatModel as OpenAIModel  # type: ignore
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai import Agent
except ImportError:  # pragma: no cover - 依赖未安装时测试环境跳过
    OpenAIModel = None  # type: ignore
    OpenAIProvider = None  # type: ignore
    Agent = None  # type: ignore


class HrDeps(BaseModel):
    """工作区/用户/对象上下文，透传给工具与系统提示词。"""

    workspace_id: str = Field(description="工作区 ID，服务端派生")
    user_id: uuid.UUID | str | None = Field(default=None, description="触发用户 ID")
    hr_role: str | None = Field(default=None, description="HR 角色")
    application_id: str | None = Field(default=None, description="Application ID")
    job_id: str | None = Field(default=None, description="Job ID")
    interview_id: str | None = Field(default=None, description="Interview ID")
    # 可选：携带脱敏后的业务对象，供工具直接返回（避免工具内再查库时重复脱敏）
    application: dict | None = Field(default=None, description="脱敏 Application 上下文")
    job: dict | None = Field(default=None, description="脱敏 Job 上下文")
    interview: dict | None = Field(default=None, description="脱敏 Interview 上下文")


def get_pydantic_model(workspace_id: str, config: HrConfig | None):
    """
    复用 runner._config/_load_llm 逻辑：经 get_model_by_id 取 Model，
    解析 credential 中的 api_base/api_key/model_name，构造 OpenAIModel。

    返回 (OpenAIModel, model_name) 或 (None, "")。
    """
    if config is None:
        try:
            config = HrConfig.objects.filter(workspace_id=workspace_id).first()
            if config is None:
                config = HrConfig.objects.create(workspace_id=workspace_id, llm_model_id="")
        except Exception:
            return None, ""
    llm_model_id = getattr(config, "llm_model_id", "") or ""
    if not llm_model_id:
        return None, ""
    try:
        from models_provider.tools import get_model_by_id
        from common.utils.rsa_util import rsa_long_decrypt

        model = get_model_by_id(llm_model_id, workspace_id)
        if getattr(model, "model_type", None) != "LLM":
            return None, ""
        credential_raw = getattr(model, "credential", "") or ""
        try:
            credential = json.loads(rsa_long_decrypt(credential_raw)) if credential_raw else {}
        except Exception:
            credential = {}
        api_base = credential.get("api_base") or credential.get("api_base_url") or ""
        api_key = credential.get("api_key") or ""
        model_name = getattr(model, "model_name", "") or llm_model_id
        if OpenAIModel is None or OpenAIProvider is None:
            return None, ""
        if not api_base or not api_key:
            return None, ""
        provider = OpenAIProvider(base_url=api_base, api_key=api_key)
        pydantic_model = OpenAIModel(model_name, provider=provider)
        return pydantic_model, model_name
    except Exception:
        return None, ""


def create_agent(model, deps_type=HrDeps, output_type=None, system_prompt: str = ""):
    """
    封装 Agent(model, deps_type=..., output_type=..., system_prompt=..., retries=1)
    单次 LLM，无 ReAct 循环。
    """
    if Agent is None:
        raise ImportError("pydantic-ai 未安装")
    kwargs: dict = {
        "model": model,
        "deps_type": deps_type,
        "system_prompt": system_prompt,
        "retries": 1,
    }
    if output_type is not None:
        kwargs["output_type"] = output_type
    return Agent(**kwargs)


__all__ = ["HrDeps", "get_pydantic_model", "create_agent", "guard_limits", "write_skipped_run", "record_prompt_version"]
