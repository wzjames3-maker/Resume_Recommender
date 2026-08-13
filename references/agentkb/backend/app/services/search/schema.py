from sqlalchemy import Integer, and_, case, cast, exists, func, or_, select

from app.models import Assignment, Candidate, CandidateRevision

SEARCH_SCHEMA_VERSION = "search/v1"

COND_FIELDS = {
    "skills": "contains", "years_experience": "range", "city": "any_match",
    "expected_city": "any_match", "highest_degree": "range_degree", "expected_position": "contains_text",
    "name": "contains_text", "level": "eq", "domain": "contains_text", "management": "eq",
    "interview_result": "eq", "assignment_status": "eq",
}
PROFILE_FIELDS = {"level", "domain", "management"}
OPS = {"contains", "contains_text", ">=", "any_match", "eq", "range_degree"}
DEGREE_ORDINAL = {"初中": 1, "高中": 2, "中专": 3, "大专": 4, "本科": 5, "硕士": 6, "博士": 7}


class SearchSchemaError(Exception):
    pass


def _validate_value(op: str, value) -> None:
    """S-4 校验：LLM 输出非法值类型（如 years_experience='5年'）在入 SQL 前拒绝。None 为 follow_up 删除标记。"""
    if value is None:
        return
    if op == "contains":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise SearchSchemaError("contains 的 value 必须为字符串数组")
    elif op == ">=":
        if not isinstance(value, int):
            raise SearchSchemaError(">= 的 value 必须为整数")
    elif op in ("any_match", "eq", "contains_text", "range_degree"):
        if not isinstance(value, str):
            raise SearchSchemaError(f"{op} 的 value 必须为字符串")
    else:
        raise SearchSchemaError(f"未知操作符: {op}")


def _validate_one(cond: dict) -> None:
    has_field = "field" in cond
    has_fields = "fields" in cond
    if has_field == has_fields:
        raise SearchSchemaError("条件必须二选一提供 field 或 fields")
    op = cond.get("op")
    if op not in OPS:
        raise SearchSchemaError(f"未知操作符: {op}")
    if "missing_policy" not in cond or cond["missing_policy"] not in ("exclude", "include"):
        raise SearchSchemaError("missing_policy 必填且为 exclude/include")
    fields = [cond["field"]] if has_field else list(cond["fields"])
    for f in fields:
        if f not in COND_FIELDS:
            raise SearchSchemaError(f"未知字段: {f}")
    if "logic" not in cond or cond["logic"] not in ("AND", "OR"):
        raise SearchSchemaError("logic 必填且为 AND/OR")
    _validate_value(op, cond.get("value"))
    if op == "eq":
        for field in fields:
            if field == "interview_result" and cond.get("value") not in {"passed", "failed", "no_show", "cancelled"}:
                raise SearchSchemaError("非法 interview_result")
            if field == "assignment_status" and cond.get("value") not in {
                "pending_screen", "screen_passed", "interviewing", "offer", "hired",
                "offer_rejected", "rejected", "closed_after_hire", "closed_by_job",
            }:
                raise SearchSchemaError("非法 assignment_status")


def validate_conditions(conditions: list) -> None:
    if not isinstance(conditions, list):
        raise SearchSchemaError("conditions 必须为数组")
    for cond in conditions:
        if not isinstance(cond, dict):
            raise SearchSchemaError("条件必须为对象")
        _validate_one(cond)


def requires_profile_join(conditions: list) -> bool:
    """画像字段（level/domain/management）存于 latest_revision.profile_json，过滤需 JOIN。"""
    return any(
        (cond.get("field") in PROFILE_FIELDS)
        or any(f in PROFILE_FIELDS for f in (cond.get("fields") or []))
        for cond in conditions
    )


def _field_expr(key: str):
    if key in PROFILE_FIELDS:
        return CandidateRevision.profile_json["values"][key].astext
    return Candidate.structured_data.op("->>")(key)


def build_condition_filter(conditions: list):
    """把条件 AST 编译为候选 SQL 谓词（S-2）。conditions 为空或全为删除标记时返回 None。

    画像字段需在调用方对 candidates JOIN latest_revision（见 requires_profile_join）。
    """
    exprs = []
    for cond in conditions:
        op = cond["op"]
        fields = [cond["field"]] if "field" in cond else list(cond["fields"])
        value = cond["value"]
        if value is None:
            continue  # follow_up 删除标记，不参与过滤
        if op == "contains" and fields == ["skills"]:
            for skill in value:
                exprs.append(Candidate.search_tsv.op("@@")(func.plainto_tsquery("simple", skill)))
        elif op == "contains_text":
            for f in fields:
                exprs.append(_field_expr(f).ilike(f"%{value}%"))
        elif op == "any_match":
            parts = [_field_expr(f) == value for f in fields]
            exprs.append(or_(*parts))
        elif op == ">=" and fields == ["years_experience"]:
            exprs.append(func.coalesce(cast(_field_expr("years_experience"), Integer), -1) >= int(value))
        elif op == "range_degree" and fields == ["highest_degree"]:
            low = DEGREE_ORDINAL.get(value)
            if low is None:
                raise SearchSchemaError(f"非法学历枚举: {value}")
            ordinal_case = case(
                *[(Candidate.structured_data.op("->>")("highest_degree") == d, o) for d, o in DEGREE_ORDINAL.items()],
                else_=0,
            )
            exprs.append(ordinal_case >= low)
        elif op == "eq":
            for f in fields:
                if f == "interview_result":
                    exprs.append(exists(select(Assignment.id).where(
                        Assignment.workspace_id == Candidate.workspace_id,
                        Assignment.candidate_id == Candidate.id,
                        Assignment.interview_result == value,
                    )))
                elif f == "assignment_status":
                    exprs.append(exists(select(Assignment.id).where(
                        Assignment.workspace_id == Candidate.workspace_id,
                        Assignment.candidate_id == Candidate.id,
                        Assignment.status == value,
                    )))
                else:
                    exprs.append(_field_expr(f) == value)
        else:
            raise SearchSchemaError(f"不支持的条件组合: {op} {fields}")
    return and_(*exprs) if exprs else None
