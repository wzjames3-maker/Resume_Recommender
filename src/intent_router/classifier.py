"""
智能招聘 RAG 推荐系统 - Intent 意图分类器
使用 prompt-based JSON extraction（不依赖 function_call）"""

import hashlib
import json
import re
import time
from typing import Any, Dict, Optional

import httpx

from src.common.config import get_settings
from src.common.errors import ErrorCode, ExternalServiceError
from src.common.logger import get_logger
from src.intent_router.schemas import (
    CandidateSlot, ConversationContext, IntentEnum, IntentResult, QuerySlot,
)

logger = get_logger("intent_classifier")

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 2
CONFIDENCE_THRESHOLD = 0.7
CACHE_TTL_SECONDS = 300


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    """从 LLM 响应中提取 JSON"""
    match = re.search(r"`{3}(?:json)?\s*(\{.*?\})\s*`{3}", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        return json.loads(text[first:last + 1])
    raise ValueError(f"Cannot parse JSON: {text[:300]}")


_INTENT_SCHEMA = """{
  "intent": "recruitment.search",
  "confidence": 0.9,
  "candidate_slots": {
    "job_title": "岗位", "skills": ["技能], "experience": 5,
    "experience_op": ">=", "education": "本科", "gender": null,
    "age": null, "age_op": null, "city": "城市",
    "industry": null, "company": null, "school": null,
    "salary": null, "salary_op": null, "language": null,
    "certificate": null, "job_type": null
  },
  "query_slots": {
    "count": 10, "sort_by": "score", "order": "desc", "page": 1, "top_k": 50
  },
  "reasoning": "推理说明"
}"""


class IntentClassifier:
    """Intent 意图分类器"""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.llm.LLM_API_KEY
        self.api_base_url = settings.llm.LLM_BASE_URL
        self.model = settings.llm.LLM_MODEL
        self.timeout = DEFAULT_TIMEOUT
        self.confidence_threshold = CONFIDENCE_THRESHOLD
        self._cache: Dict[str, tuple] = {}

    def classify(self, query: str, context: Optional[ConversationContext] = None) -> IntentResult:
        cache_key = self._cache_key(query, context)
        cached = self._from_cache(cache_key)
        if cached:
            return cached
        result = self._call_llm(query, context)
        self._to_cache(cache_key, result)
        return result

    def _call_llm(self, query: str, context: Optional[ConversationContext]) -> IntentResult:
        prompt = self._build_prompt(query, context)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是智能招聘助手的意图识别模块。只输出合法JSON，不输出其他文字。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }
        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(f"{self.api_base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code != 200:
                    if attempt < MAX_RETRIES:
                        continue
                    raise ExternalServiceError(error_code=ErrorCode.SYS_005, detail=f"Intent API {resp.status_code}")
                data = resp.json()
                msg = data["choices"][0]["message"]
                # Try function_call first
                fc = msg.get("function_call")
                if fc and fc.get("arguments"):
                    args = json.loads(fc["arguments"])
                else:
                    content = msg.get("content", "{}")
                    args = _extract_json_from_text(content)
                return self._parse(args, query)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(f"JSON parse failed ({attempt+1}): {exc}")
                if attempt < MAX_RETRIES:
                    continue
                return self._keyword_fallback(query)
            except Exception as exc:
                logger.warning(f"Intent API error ({attempt+1}): {exc}")
                if attempt < MAX_RETRIES:
                    continue
                return self._keyword_fallback(query)
        return self._keyword_fallback(query)

    def _build_prompt(self, query: str, context: Optional[ConversationContext]) -> str:
        prompt = (
            "请识别以下用户输入的意图，并提取候选人属性Slots。\n"
            "意图类型说明：\n"
            "- recruitment.search: 候选人检索（如\"帮我找3年Java开发\"）\n"
            "- recruitment.refine: 条件修正（如\"按薪资排序\"、\"再推荐几个\"）\n"
            "- recruitment.compare: 候选人对比（如\"对比张三和李四\"）\n"
            "- candidate.lookup: 详情查看（如\"张三的简历详情\"）\n"
            "- resume.upload: 简历上传\n"
            "- resume.manage: 简历管理\n"
            "- knowledge.qa: 知识问答\n"
            "- analytics: 数据统计\n"
            "- chat: 闲聊（如\"你好\"、\"今天天气怎么样\"）\n"
            "- fallback: 无法识别\n\n"
            f"JSON输出格式：\n{_INTENT_SCHEMA}\n\n"
            f"用户输入：{query}"
        )
        if context:
            prompt += f"\n\n对话上下文：轮次={context.turn_count}, 上次意图={context.last_intent}"
        return prompt

    def _parse(self, args: Dict[str, Any], query: str) -> IntentResult:
        intent_str = args.get("intent", "fallback")
        try:
            intent = IntentEnum(intent_str)
        except ValueError:
            # Try partial match
            for member in IntentEnum:
                if member.value == intent_str or intent_str in member.value:
                    intent = member
                    break
            else:
                intent = IntentEnum.FALLBACK
        confidence = max(0.0, min(1.0, args.get("confidence", 0.5)))
        cs_data = args.get("candidate_slots", {})
        if isinstance(cs_data, dict):
            # Filter out unknown fields
            valid_fields = set(CandidateSlot.model_fields.keys())
            filtered = {k: v for k, v in cs_data.items() if k in valid_fields and v is not None}
            candidate_slots = CandidateSlot(**filtered)
        else:
            candidate_slots = CandidateSlot()
        qs_data = args.get("query_slots", {})
        if isinstance(qs_data, dict):
            valid_fields = set(QuerySlot.model_fields.keys())
            filtered = {k: v for k, v in qs_data.items() if k in valid_fields and v is not None}
            query_slots = QuerySlot(**filtered)
        else:
            query_slots = QuerySlot()
        reasoning = args.get("reasoning", "")
        return IntentResult(
            intent=intent, confidence=confidence,
            candidate_slots=candidate_slots, query_slots=query_slots,
            raw_query=query, reasoning=reasoning,
        )

    def _keyword_fallback(self, query: str) -> IntentResult:
        q = query.lower()
        rules = [
            (IntentEnum.RECRUITMENT_SEARCH, ["找", "推荐", "招聘", "搜索", "招", "需要"]),
            (IntentEnum.RECRUITMENT_REFINE, ["排序", "筛选", "过滤", "修改", "调整"]),
            (IntentEnum.CANDIDATE_LOOKUP, ["详情", "简历", "查看", "介绍"]),
            (IntentEnum.RESUME_UPLOAD, ["上传", "导入"]),
            (IntentEnum.CHAT, ["你好", "hi", "hello", "天气", "谢谢"]),
        ]
        for intent, keywords in rules:
            for kw in keywords:
                if kw in q:
                    return IntentResult(
                        intent=intent, confidence=0.6,
                        candidate_slots=CandidateSlot(), query_slots=QuerySlot(),
                        raw_query=query, reasoning=f"keyword: {kw}",
                    )
        return IntentResult(
            intent=IntentEnum.CHAT, confidence=0.5,
            candidate_slots=CandidateSlot(), query_slots=QuerySlot(),
            raw_query=query, reasoning="no keyword matched",
        )

    def _cache_key(self, query: str, ctx: Optional[ConversationContext]) -> str:
        s = query
        if ctx:
            s += f"|{ctx.conversation_id}|{ctx.turn_count}"
            if ctx.last_intent:
                s += f"|{ctx.last_intent.value}"
        return hashlib.md5(s.encode()).hexdigest()

    def _from_cache(self, key: str) -> Optional[IntentResult]:
        if key not in self._cache:
            return None
        result, ts = self._cache[key]
        if time.time() - ts > CACHE_TTL_SECONDS:
            del self._cache[key]
            return None
        return result

    def _to_cache(self, key: str, result: IntentResult):
        self._cache[key] = (result, time.time())

    def clear_cache(self):
        self._cache.clear()

    def set_confidence_threshold(self, threshold: float):
        self.confidence_threshold = max(0.0, min(1.0, threshold))


intent_classifier = IntentClassifier()


def get_intent_classifier() -> IntentClassifier:
    return intent_classifier
