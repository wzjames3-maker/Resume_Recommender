import pytest

from app.services.search.schema import (
    SearchSchemaError,
    build_condition_filter,
    validate_conditions,
)


def _conds():
    return [
        {"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"},
        {"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"},
        {"fields": ["city", "expected_city"], "op": "any_match", "value": "杭州", "logic": "AND", "missing_policy": "exclude"},
    ]


def test_valid_conditions_pass():
    validate_conditions(_conds())


def test_unknown_field_rejected():
    with pytest.raises(SearchSchemaError, match="未知字段"):
        validate_conditions([{"field": "salary", "op": ">=", "value": 100, "logic": "AND", "missing_policy": "exclude"}])


def test_missing_missing_policy_rejected():
    with pytest.raises(SearchSchemaError, match="missing_policy"):
        validate_conditions([{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND"}])


def test_both_field_and_fields_rejected():
    with pytest.raises(SearchSchemaError, match="field 或 fields"):
        validate_conditions([{"field": "skills", "fields": ["city"], "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}])


def test_build_condition_filter_compiles_sql():
    from sqlalchemy.dialects import postgresql

    expr = build_condition_filter(_conds())
    compiled = str(expr.compile(dialect=postgresql.dialect()))
    assert "->>" in compiled
    assert "plainto_tsquery" in compiled

def test_invalid_value_type_rejected():
    with pytest.raises(SearchSchemaError, match="整数"):
        validate_conditions([{"field": "years_experience", "op": ">=", "value": "5年", "logic": "AND", "missing_policy": "exclude"}])
    with pytest.raises(SearchSchemaError, match="字符串数组"):
        validate_conditions([{"field": "skills", "op": "contains", "value": "Java", "logic": "AND", "missing_policy": "exclude"}])


def test_none_value_allowed_as_removal_marker():
    validate_conditions([{"field": "years_experience", "op": ">=", "value": None, "logic": "AND", "missing_policy": "exclude"}])
