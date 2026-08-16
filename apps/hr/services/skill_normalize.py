# coding=utf-8
"""
    @project: MaxKB
    @file： skill_normalize.py
    @date：2026/8/16
    @desc：技能词归一（T5）：大小写/空白/常见变体 → 规范形，支撑 candidate_skill 表与 Skill-AND SQL。
          别名表：apps/hr/data/skill_alias.json（初版 ~100 条，源自 Job.skill_requirements 聚合 + 人工；
          治理：LLM 抽取 + 人工抽检 + 字典冻结）。
"""
import json
import os

_SKILL_ALIAS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "skill_alias.json")

with open(_SKILL_ALIAS_FILE, encoding="utf-8") as _f:
    _ALIAS_MAP = json.load(_f)


def normalize_skill(skill):
    """技能词归一：去空白、小写、查别名表；未命中返回小写原词。"""
    if not skill or not isinstance(skill, str):
        return ""
    key = " ".join(skill.strip().split()).lower()
    if not key:
        return ""
    return _ALIAS_MAP.get(key, key)
