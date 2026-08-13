from app.services.search.context import (
    deserialize_context,
    merge_follow_up,
    serialize_context,
)


def _java_cond():
    return {"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}


def test_follow_up_keeps_prior_and_applies_change():
    prior = [_java_cond(), {"field": "years_experience", "op": ">=", "value": 3, "logic": "AND", "missing_policy": "exclude"}]
    change = [{"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"}]
    merged = merge_follow_up(prior, change)
    assert _java_cond() in merged
    assert any(c["field"] == "years_experience" and c["value"] == 5 for c in merged)


def test_follow_up_removes_none_condition():
    prior = [_java_cond(), {"fields": ["city", "expected_city"], "op": "any_match", "value": "杭州", "logic": "AND", "missing_policy": "exclude"}]
    merged = merge_follow_up(prior, [{"fields": ["city", "expected_city"], "op": "any_match", "value": None, "logic": "AND", "missing_policy": "include"}])
    assert not any(c.get("fields") == ["city", "expected_city"] for c in merged)


def test_context_serialize_roundtrip():
    ctx = {"conditions": [_java_cond()], "pool_scope": "active", "requested_count": None}
    assert deserialize_context(serialize_context(ctx)) == ctx