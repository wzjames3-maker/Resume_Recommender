import pytest

from app.services.search.extractor import (
    INTENTS,
    SearchExtractionError,
    extract_search_intent,
    validate_intent_output,
)


def test_valid_search_output_passes():
    output = {
        "intent": "search",
        "requested_count": None,
        "pool_scope": "active",
        "conditions": [
            {"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"},
        ],
        "reason": "用户要求 Java 技能",
    }
    validate_intent_output(output)


def test_unknown_intent_rejected():
    with pytest.raises(SearchExtractionError, match="intent"):
        validate_intent_output({"intent": "hack", "requested_count": None, "pool_scope": "active", "conditions": [], "reason": ""})


def test_unknown_pool_scope_rejected():
    with pytest.raises(SearchExtractionError, match="pool_scope"):
        validate_intent_output({"intent": "search", "requested_count": None, "pool_scope": "hired_pool", "conditions": [], "reason": ""})


def test_requested_count_only_for_candidate_intents():
    with pytest.raises(SearchExtractionError, match="requested_count"):
        validate_intent_output({"intent": "chit_chat", "requested_count": 5, "pool_scope": None, "conditions": [], "reason": ""})


def test_intents_enum():
    assert {"search", "follow_up", "job_search", "statistics", "write_request", "chit_chat", "out_of_scope"} <= INTENTS


@pytest.mark.asyncio
async def test_extract_search_intent_calls_llm():
    class FakeLLM:
        async def chat_json(self, system, user, schema):
            return {"intent": "search", "requested_count": 5, "pool_scope": "active",
                    "conditions": [{"field": "skills", "op": "contains", "value": ["Java"], "logic": "AND", "missing_policy": "exclude"}],
                    "reason": "找 5 个 Java 人"}

    out = await extract_search_intent(FakeLLM(), "找 5 个 Java 人", prior_conditions=None)
    assert out.intent == "search"
    assert out.requested_count == 5
    assert out.conditions[0]["field"] == "skills"

def test_job_ref_only_for_job_search_intent():
    with pytest.raises(SearchExtractionError, match="job"):
        validate_intent_output({"intent": "search", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "job_id": 1, "job_title": None, "reason": ""})


def test_job_search_accepts_job_ref_and_count():
    validate_intent_output({"intent": "job_search", "requested_count": 20, "pool_scope": "active",
                            "conditions": [], "job_id": 5, "job_title": None, "reason": ""})
    validate_intent_output({"intent": "job_search", "requested_count": None, "pool_scope": "active",
                            "conditions": [], "job_id": None, "job_title": "前端开发", "reason": ""})


def test_job_id_must_be_positive_int():
    with pytest.raises(SearchExtractionError, match="job_id"):
        validate_intent_output({"intent": "job_search", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "job_id": -1, "job_title": None, "reason": ""})


def test_statistics_accepts_stat_group_by():
    validate_intent_output({"intent": "statistics", "requested_count": None, "pool_scope": "active",
                            "conditions": [], "stat_group_by": "city", "reason": "城市分布"})
    validate_intent_output({"intent": "statistics", "requested_count": None, "pool_scope": "active",
                            "conditions": [], "stat_group_by": None, "reason": "仅计数"})


def test_stat_group_by_rejected_outside_statistics():
    with pytest.raises(SearchExtractionError, match="stat_group_by"):
        validate_intent_output({"intent": "search", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "stat_group_by": "city", "reason": ""})


def test_statistics_rejects_unknown_dimension():
    with pytest.raises(SearchExtractionError, match="stat_group_by"):
        validate_intent_output({"intent": "statistics", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "stat_group_by": "salary", "reason": ""})


def test_statistics_rejects_requested_count():
    with pytest.raises(SearchExtractionError, match="requested_count"):
        validate_intent_output({"intent": "statistics", "requested_count": 5, "pool_scope": "active",
                                "conditions": [], "stat_group_by": None, "reason": ""})


def test_statistics_rejects_unhashable_stat_group_by():
    with pytest.raises(SearchExtractionError, match="stat_group_by"):
        validate_intent_output({"intent": "statistics", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "stat_group_by": ["city"], "reason": ""})

def test_statistics_rejects_job_ref():
    with pytest.raises(SearchExtractionError, match="job"):
        validate_intent_output({"intent": "statistics", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "stat_group_by": None, "job_id": 1, "job_title": None, "reason": ""})


def test_search_accepts_offer_rejected_history_predicate():
    validate_intent_output({"intent": "search", "requested_count": None, "pool_scope": "active",
                            "conditions": [], "assignment_history": [{"event": "offer_rejected"}],
                            "reason": "曾拒绝 offer"})


def test_search_rejects_unknown_top_level_field():
    with pytest.raises(SearchExtractionError, match="未知字段"):
        validate_intent_output({"intent": "search", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "unknown": "ignored", "reason": ""})


def test_search_rejects_invalid_history_predicate():
    with pytest.raises(SearchExtractionError, match="assignment_history"):
        validate_intent_output({"intent": "search", "requested_count": None, "pool_scope": "active",
                                "conditions": [], "assignment_history": [{"event": "salary_change"}],
                                "reason": ""})
