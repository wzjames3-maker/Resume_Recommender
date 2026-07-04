"""
智能招聘 RAG 推荐系统 - 推荐理由生成模块

变更 (Tier L): 使用 LLM 生成自然语言推荐理由（非模板字符串拼接）
"""

import json
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from src.common.config import get_settings
from src.common.logger import get_logger
from src.intent_router.schemas import CandidateSlot
from src.recommendation_engine.context_builder import get_context_builder
from src.recommendation_engine.hybrid_retriever import RetrievalResult

logger = get_logger(__name__)


class ReasonResult:
    """推荐理由结果"""

    def __init__(
        self,
        reason: str,
        matched_skills: List[str],
        missing_skills: List[str],
        score_breakdown: Dict[str, float],
    ):
        self.reason = reason
        self.matched_skills = matched_skills
        self.missing_skills = missing_skills
        self.score_breakdown = score_breakdown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason": self.reason,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "score_breakdown": self.score_breakdown,
        }


SYSTEM_PROMPT = """你是招聘推荐顾问。根据已有信息客观评估候选人匹配度。

要求：
1. reason: 具体说明匹配点和不足点，引用简历中的实际经验/技能/学历，不要泛泛而谈
2. matched_skills: 候选人与招聘需求匹配的特定技能
3. missing_skills: 候选人不具备的关键技能
4. score_breakdown: 0.0-1.0评分
   - skill_match: 技能重叠度
   - experience_match: 工作经验与相关度
   - education_match: 学历/学校匹配
   - project_relevance: 过往工作/项目与目标岗位内容相关性
   - industry_match: 所处行业/公司类型匹配度

严格输出JSON，不要额外文字。"""


class ReasonGenerator:
    """推荐理由生成器 — LLM 驱动"""

    def __init__(self):
        settings = get_settings()
        self.context_builder = get_context_builder()
        self.llm_client = OpenAI(
            api_key=settings.llm.LLM_API_KEY,
            base_url=settings.llm.LLM_BASE_URL,
        )
        self.model = settings.llm.LLM_MODEL
        self._fallback = False

    def generate(
        self,
        result: RetrievalResult,
        slots: CandidateSlot,
    ) -> ReasonResult:
        """生成推荐理由"""

        # 构建上下文
        ctx = self.context_builder.build(result, slots)
        prompt_text = ctx.to_prompt_text()

        try:
            return self._call_llm(prompt_text, result, slots)
        except Exception as e:
            logger.warning(f"LLM 推荐理由生成失败，降级为模板化理由: {e}")
            return self._fallback_reason(result, slots)

    def _call_llm(
        self,
        prompt_text: str,
        result: RetrievalResult,
        slots: CandidateSlot,
    ) -> ReasonResult:
        """调用 LLM 生成推荐理由"""
        response = self.llm_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_text},
            ],
            temperature=0.3,
            max_tokens=2048,
        )

        raw = response.choices[0].message.content or "{}"
        data = self._parse_json(raw)

        return ReasonResult(
            reason=data.get("reason", ""),
            matched_skills=data.get("matched_skills", []),
            missing_skills=data.get("missing_skills", []),
            score_breakdown={
                "skill_match": float(data.get("score_breakdown", {}).get("skill_match", 0)),
                "experience_match": float(data.get("score_breakdown", {}).get("experience_match", 0)),
                "education_match": float(data.get("score_breakdown", {}).get("education_match", 0)),
                "project_relevance": float(data.get("score_breakdown", {}).get("project_relevance", 0)),
                "industry_match": float(data.get("score_breakdown", {}).get("industry_match", 0)),
            },
        )

    def _parse_json(self, raw: str) -> Dict[str, Any]:
        text = raw.strip()
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()
        if not text.startswith("{"):
            first = text.find("{")
            last = text.rfind("}")
            if first != -1 and last > first:
                text = text[first:last + 1]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                text = re.sub(r",\s*}", "}", text)
                text = re.sub(r",\s*]", "]", text)
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        logger.warning(f"无法解析 LLM 输出 JSON: {raw[:200]}")
        return {}

    def _fallback_reason(
        self,
        result: RetrievalResult,
        slots: CandidateSlot,
    ) -> ReasonResult:
        """LLM 不可用时的模板化降级理由"""
        m = result.metadata
        name = m.get("candidate_name", "该候选人")
        req_skills = getattr(slots, "skills", None) or []
        candidate_skills = m.get("skills_normalized", [])
        exp = m.get("years_of_experience", 0)

        req_set = set(s.lower() for s in req_skills)
        cand_set = set(s.lower() for s in candidate_skills)
        matched = [s for s in req_skills if s.lower() in cand_set]
        missing = [s for s in req_skills if s.lower() not in cand_set]

        req_exp = getattr(slots, "experience", None)
        reason = f"{name}，匹配技能: {', '.join(matched) if matched else '无'}，"
        if missing:
            reason += f"缺失: {', '.join(missing)}，"
        reason += f"{exp}年经验。匹配度: {result.score:.0%}（模板化理由）"

        return ReasonResult(
            reason=reason,
            matched_skills=matched,
            missing_skills=missing,
            score_breakdown={
                "skill_match": len(matched) / max(len(req_skills), 1),
                "experience_match": min(exp / max(float(req_exp or 1), 1), 1.0),
                "education_match": 0.5,
                "project_relevance": 0.5,
                "industry_match": 0.5,
            },
        )


_reason_generator: Optional[ReasonGenerator] = None


def get_reason_generator() -> ReasonGenerator:
    global _reason_generator
    if _reason_generator is None:
        _reason_generator = ReasonGenerator()
    return _reason_generator
