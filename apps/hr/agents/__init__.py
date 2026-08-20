# coding=utf-8
"""
    @project: MaxKB
    @file： __init__.py
    @date：2026/8/17
    @desc: Agent 运行时（D1 Screening）：Runner / 工具上下文投影 / 服务端评分 / Proposal 审批。
           Pydantic AI 基础设施见 pydantic_base.py。
"""
from hr.agents.pydantic_base import HrDeps, create_agent, get_pydantic_model

__all__ = ["HrDeps", "create_agent", "get_pydantic_model"]
