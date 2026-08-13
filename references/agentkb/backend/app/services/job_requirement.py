from app.services.search.schema import (
    SEARCH_SCHEMA_VERSION,
    SearchSchemaError,
    validate_conditions,
)

JOB_REQUIREMENT_PROMPT_VERSION = "job-req-prompt/v1"

JOB_REQUIREMENT_SYSTEM_PROMPT = f"""你是招聘职位要求解析器。输入岗位要求的自然语言描述，输出严格 JSON（schema_version={SEARCH_SCHEMA_VERSION}）。

把描述中明确出现的岗位要求解析为检索条件，仅使用以下字段（与搜人条件一致）:
- skills contains (数组值)
- years_experience >= (整数)
- city any_match（描述提到城市时，fields: ["city","expected_city"]）
- highest_degree range_degree（值：初中/高中/中专/大专/本科/硕士/博士）
- expected_position contains_text
- level / management eq（画像字段）
- domain contains_text

规则:
1. 仅输出描述中明确出现的条件；未出现在描述中的条件不得输出，禁止编造。
2. 每条条件必须给出 evidence，locator 为描述中对应的原文句段。
3. 每条条件含 logic（AND/OR）与 missing_policy（exclude/include）。
4. 描述无明确要求时 conditions 为空数组。
输出: {{"conditions": [...], "evidence": {{"<字段>": {{"locator": "原文句段", "reason": "..."}}}}, "reason": "..."}}"""


def condition_key(cond: dict) -> str:
    """条件主字段：field 或 fields 首项（用于 override 定位）。"""
    return cond.get("field") if "field" in cond else cond["fields"][0]


def _validate_parsed(parsed: dict) -> dict:
    if not isinstance(parsed, dict):
        raise SearchSchemaError("解析结果必须为对象")
    conditions = parsed.get("conditions") or []
    validate_conditions(conditions)
    evidence = parsed.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise SearchSchemaError("evidence 必须为对象")
    for cond in conditions:
        key = condition_key(cond)
        entry = evidence.get(key)
        if not isinstance(entry, dict) or not entry.get("locator"):
            raise SearchSchemaError(f"条件 {key} 缺少 evidence.locator")
    return {"conditions": conditions, "evidence": evidence, "reason": parsed.get("reason") or ""}


async def parse_job_requirement(llm, description: str) -> dict:
    """岗位描述 → 严格条件 AST（复用 search/schema.validate_conditions）。"""
    raw = await llm.chat_json(JOB_REQUIREMENT_SYSTEM_PROMPT, description, {})
    return _validate_parsed(raw)


def apply_condition_overrides(base: list, overrides: list) -> list:
    """按条件主字段替换/清除。后写覆盖先写；clear 删除该字段条件。"""
    merged = [dict(c) for c in base]
    for ov in overrides:
        key = ov["field_path"]
        action = ov["action"]
        if action == "clear":
            merged = [c for c in merged if condition_key(c) != key]
        elif action == "override":
            after = dict(ov["after_value"])
            validate_conditions([after])
            if condition_key(after) != key:
                raise SearchSchemaError("override 条件主字段与 field_path 不一致")
            replaced = False
            for i, c in enumerate(merged):
                if condition_key(c) == key:
                    merged[i] = after
                    replaced = True
                    break
            if not replaced:
                merged.append(after)
    return merged


def resolve_effective_ast(revision, overrides: list) -> list:
    """最新 revision 解析 AST + 字段级 override 合并（J-6）。"""
    base = list(revision.parsed_ast or [])
    return apply_condition_overrides(base, [
        {"field_path": o.field_path, "action": o.action.value, "after_value": o.after_value}
        for o in overrides
    ])