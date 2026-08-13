from dataclasses import dataclass

from app.services.search.schema import (
    SEARCH_SCHEMA_VERSION,
    SearchSchemaError,
    validate_conditions,
)

INTENTS = {"search", "follow_up", "job_search", "statistics", "write_request", "chit_chat", "out_of_scope"}
POOL_SCOPES = {"active", "rejected", "hired", None}
STAT_GROUP_BY = {"city", "expected_city", "highest_degree", "years_experience",
                 "expected_position", "level", "domain", "management"}
_COUNT_INTENTS = {"search", "follow_up", "job_search"}  # 数量意图：候选 + 按岗位
_JOB_INTENTS = {"job_search"}  # job_id/job_title 仅 job_search 携带
SEARCH_PROMPT_VERSION = "search-prompt/v1"


class SearchExtractionError(Exception):
    pass


@dataclass
class SearchIntent:
    intent: str
    conditions: list
    requested_count: int | None
    pool_scope: str | None
    job_id: int | None
    job_title: str | None
    reason: str
    stat_group_by: str | None = None
    assignment_history: list[dict] | None = None
    interview_result: str | None = None
    assignment_status: str | None = None


def validate_intent_output(raw: dict) -> None:
    allowed_keys = {"intent", "conditions", "requested_count", "pool_scope", "job_id", "job_title",
                    "stat_group_by", "assignment_history", "reason", "interview_result", "assignment_status"}
    unknown_keys = set(raw) - allowed_keys
    if unknown_keys:
        raise SearchExtractionError(f"未知字段: {sorted(unknown_keys)}")
    intent = raw.get("intent")
    if intent not in INTENTS:
        raise SearchExtractionError(f"非法 intent: {intent}")
    if raw.get("pool_scope") not in POOL_SCOPES:
        raise SearchExtractionError(f"非法 pool_scope: {raw.get('pool_scope')}")
    conditions = raw.get("conditions") or []
    try:
        validate_conditions(conditions)
    except SearchSchemaError as exc:
        raise SearchExtractionError(str(exc)) from exc
    requested = raw.get("requested_count")
    if requested is not None:
        if intent not in _COUNT_INTENTS:
            raise SearchExtractionError("requested_count 仅候选/按岗位意图可携带")
        if not isinstance(requested, int) or requested <= 0:
            raise SearchExtractionError("requested_count 必须为正整数")
    job_id, job_title = raw.get("job_id"), raw.get("job_title")
    if intent not in _JOB_INTENTS:
        if job_id is not None or job_title is not None:
            raise SearchExtractionError("job_id/job_title 仅 job_search 意图可携带")
    else:
        if job_id is not None and (not isinstance(job_id, int) or job_id <= 0):
            raise SearchExtractionError("job_id 必须为正整数")
        if job_title is not None and not isinstance(job_title, str):
            raise SearchExtractionError("job_title 必须为字符串")
    stat_group_by = raw.get("stat_group_by")
    if intent != "statistics":
        if stat_group_by is not None:
            raise SearchExtractionError("stat_group_by 仅统计意图可携带")
    elif stat_group_by is not None and (not isinstance(stat_group_by, str) or stat_group_by not in STAT_GROUP_BY):
        raise SearchExtractionError(f"非法 stat_group_by: {stat_group_by}")
    history = raw.get("assignment_history")
    if history is not None and (not isinstance(history, list) or any(
        not isinstance(item, dict) or set(item) != {"event"} or item["event"] != "offer_rejected"
        for item in history
    )):
        raise SearchExtractionError("非法 assignment_history")
    if raw.get("interview_result") not in (None, "passed", "failed", "no_show", "cancelled"):
        raise SearchExtractionError("非法 interview_result")
    if raw.get("assignment_status") not in (None, "pending_screen", "screen_passed", "interviewing",
                                             "offer", "hired", "offer_rejected", "rejected",
                                             "closed_after_hire", "closed_by_job"):
        raise SearchExtractionError("非法 assignment_status")


SEARCH_SYSTEM_PROMPT = f"""你是招聘搜人意图解析器。输入用户自然语言、上一轮条件（可为空）与可选的候选职位列表，输出严格 JSON（schema_version={SEARCH_SCHEMA_VERSION}）。

意图枚举:
- search: 全新人事查询
- follow_up: 在上一轮条件基础上追问/收敛（仅更新变化字段）
- job_search: 按岗位搜索（用户提到职位/岗位时）
- statistics: 统计查询（输出 stat_group_by 分布维度，null 为仅计数）
- write_request: 写请求/批量操作（不得执行）
- chit_chat: 闲聊
- out_of_scope: 超出范围

条件字段与操作符（每项含 logic 与 missing_policy）:
- skills contains (数组值)
- years_experience >= (整数)
- city / expected_city any_match（fields: ["city","expected_city"]）
- highest_degree range_degree（值：初中/高中/中专/大专/本科/硕士/博士）
- expected_position contains_text
- name contains_text
- level / management eq（画像字段）
- domain contains_text
- interview_result eq（passed/failed/no_show/cancelled）
- assignment_status eq（pending_screen/screen_passed/interviewing/offer/hired/offer_rejected/rejected/closed_after_hire/closed_by_job）

规则:
1. 仅输出上述字段，不得输出未知字段。
2. 无法从查询确定的条件不输出；禁止编造条件。
3. requested_count 为数量意图（如"找 5 个"），无数量为 null；job_search 也可带 requested_count。
4. pool_scope 为 active（默认）/ rejected（显式指定"已面试未通过/淘汰池"）/ hired（显式指定"入职员工库"）。
5. follow_up 时 pool_scope、requested_count 保持上一轮值；job_id/job_title 仅 job_search 携带。
6. job_search 时：候选职位列表存在且用户选择其中一个（如"第 1 个"或给出职位编号 #5）→ 输出对应 job_id；用户提到职位名称 → 输出 job_title；两者都无 → job_id/job_title 为 null。
7. statistics 意图输出 stat_group_by：分布维度（city/expected_city/highest_degree/years_experience/expected_position/level/domain/management）或 null（仅计数）；statistics 不携带 requested_count。
8. 默认不查询面试不通过、拒绝 Offer、已入职和已关闭流程；只有用户明确提及时才输出 interview_result 或 assignment_status。
9. assignment_history 仅支持 {{"event":"offer_rejected"}}，先按 pool_scope ACL 过滤再执行历史谓词；没有历史条件时输出空数组。
输出: {{"intent": "...", "requested_count": int|null, "pool_scope": "...", "job_id": int|null, "job_title": str|null, "stat_group_by": "city"|null, "assignment_history": [], "conditions": [...], "reason": "..."}}"""


async def extract_search_intent(llm, utterance: str, prior_conditions: list | None,
                                job_candidates: list | None = None) -> SearchIntent:
    prior_text = "" if not prior_conditions else f"上一轮条件: {prior_conditions}"
    candidates_text = "" if not job_candidates else f"候选职位列表: {job_candidates}"
    raw = await llm.chat_json(SEARCH_SYSTEM_PROMPT,
                              f"上一轮条件库: {prior_text}\n{candidates_text}\n用户: {utterance}", {})
    if not isinstance(raw, dict):
        raise SearchExtractionError("LLM 输出必须为对象")
    validate_intent_output(raw)
    return SearchIntent(
        intent=raw["intent"], conditions=raw.get("conditions") or [],
        requested_count=raw.get("requested_count"), pool_scope=raw.get("pool_scope"),
        job_id=raw.get("job_id"), job_title=raw.get("job_title"),
        stat_group_by=raw.get("stat_group_by"),
        reason=raw.get("reason") or "",
        assignment_history=raw.get("assignment_history") or [],
        interview_result=raw.get("interview_result"),
        assignment_status=raw.get("assignment_status"),
    )
