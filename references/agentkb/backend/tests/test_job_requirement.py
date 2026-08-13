import pytest

from app.services.search.schema import SearchSchemaError


@pytest.mark.asyncio
async def test_parse_job_requirement_returns_conditions():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {
                "conditions": [
                    {"field": "skills", "op": "contains", "value": ["Vue", "React"], "logic": "AND", "missing_policy": "exclude"},
                    {"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"},
                ],
                "evidence": {
                    "skills": {"locator": "精通 Vue/React", "reason": "技能要求"},
                    "years_experience": {"locator": "5 年经验", "reason": "年限要求"},
                },
                "reason": "来自岗位描述",
            }

    from app.services.job_requirement import parse_job_requirement
    parsed = await parse_job_requirement(FakeLLM(), "5 年经验，精通 Vue/React")
    assert len(parsed["conditions"]) == 2
    assert parsed["evidence"]["skills"]["locator"] == "精通 Vue/React"


@pytest.mark.asyncio
async def test_parse_rejects_condition_without_evidence():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {
                "conditions": [
                    {"field": "skills", "op": "contains", "value": ["Go"], "logic": "AND", "missing_policy": "exclude"},
                ],
                "evidence": {"other": {"locator": "x"}},
                "reason": "",
            }

    from app.services.job_requirement import parse_job_requirement
    with pytest.raises(SearchSchemaError, match="evidence"):
        await parse_job_requirement(FakeLLM(), "精通 Go")


@pytest.mark.asyncio
async def test_parse_rejects_invalid_condition():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"conditions": [{"field": "skills", "op": ">"}], "evidence": {}, "reason": ""}

    from app.services.job_requirement import parse_job_requirement
    with pytest.raises(SearchSchemaError):
        await parse_job_requirement(FakeLLM(), "x")


def test_apply_condition_overrides_replace_and_clear():
    from app.services.job_requirement import apply_condition_overrides
    base = [
        {"field": "skills", "op": "contains", "value": ["Vue"], "logic": "AND", "missing_policy": "exclude"},
        {"field": "years_experience", "op": ">=", "value": 5, "logic": "AND", "missing_policy": "exclude"},
    ]
    merged = apply_condition_overrides(base, [
        {"field_path": "skills", "action": "override",
         "after_value": {"field": "skills", "op": "contains", "value": ["Vue", "React"], "logic": "AND", "missing_policy": "exclude"}},
        {"field_path": "years_experience", "action": "clear", "after_value": None},
    ])
    assert merged[0]["value"] == ["Vue", "React"]
    assert all(c["field"] != "years_experience" for c in merged)


def test_apply_condition_overrides_adds_missing_field():
    from app.services.job_requirement import apply_condition_overrides
    merged = apply_condition_overrides([], [
        {"field_path": "city", "action": "override",
         "after_value": {"fields": ["city", "expected_city"], "op": "any_match", "value": "杭州", "logic": "AND", "missing_policy": "exclude"}},
    ])
    assert merged[0]["value"] == "杭州"