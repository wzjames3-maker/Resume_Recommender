"""
智能招聘 RAG 推荐系统 - Context Builder

构建 LLM 推荐理由生成的结构化上下文。
从 chunk.metadata 提取候选人信息（无需 MongoDB N+1 查询），
整合检索命中的 Parent Chunk 内容。
"""

from typing import Any, Dict, List, Optional

from src.common.logger import get_logger
from src.intent_router.schemas import CandidateSlot
from src.recommendation_engine.hybrid_retriever import RetrievalResult

logger = get_logger(__name__)

MAX_TOKENS = 4000


class LLMContext:
    """LLM 推荐理由生成的上下文"""

    def __init__(
        self,
        candidate_info: str,
        matched_content: str,
        candidate_skills: List[str],
        job_requirements: str,
    ):
        self.candidate_info = candidate_info
        self.matched_content = matched_content
        self.candidate_skills = candidate_skills
        self.job_requirements = job_requirements

    def to_prompt_text(self) -> str:
        """转换为 Prompt 文本"""
        parts = [
            f"=== 候选人信息 ===",
            self.candidate_info,
            "",
            f"=== 简历匹配内容 ===",
            self._truncate(self.matched_content, 3000),
            "",
            f"=== 候选人技能 ===",
            ", ".join(self.candidate_skills[:20]) if self.candidate_skills else "未知",
            "",
            f"=== 招聘需求 ===",
            self.job_requirements,
        ]
        return "\n".join(parts)

    def _truncate(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...（已截断）"


class ContextBuilder:
    """上下文构建器"""

    def build(
        self,
        result: RetrievalResult,
        slots: CandidateSlot,
    ) -> LLMContext:
        """从检索结果构建 LLM 上下文"""
        m = result.metadata

        # 候选人信息
        info_parts = []
        name = m.get("candidate_name", "")
        title = m.get("current_title", "")
        company = m.get("current_company", "")
        city = m.get("city", "")
        exp = m.get("years_of_experience", 0)
        edu = m.get("highest_education", "")
        skills = m.get("skills_normalized", [])

        if name:
            info_parts.append(f"姓名: {name}")
        if title:
            info_parts.append(f"职位: {title}")
        if company:
            info_parts.append(f"公司: {company}")
        if city:
            info_parts.append(f"城市: {city}")
        if exp:
            info_parts.append(f"工作年限: {exp}年")
        if edu:
            info_parts.append(f"最高学历: {edu}")
        candidate_info = " | ".join(info_parts) if info_parts else "未知"

        # 匹配内容
        matched_content = result.content or ""

        # 候选人技能
        candidate_skills = skills or m.get("skills_original", [])

        # 招聘需求
        req_parts = []
        job_title = getattr(slots, "job_title", None)
        req_skills = getattr(slots, "skills", None) or []
        req_exp = getattr(slots, "experience", None)
        req_edu = getattr(slots, "education", None)
        req_city = getattr(slots, "city", None)

        if job_title:
            req_parts.append(f"岗位: {job_title}")
        if req_skills:
            req_parts.append(f"要求技能: {', '.join(req_skills)}")
        if req_exp is not None:
            req_parts.append(f"要求经验: {int(req_exp)}年以上")
        if req_edu:
            edu_str = req_edu.value if hasattr(req_edu, "value") else str(req_edu)
            req_parts.append(f"要求学历: {edu_str}及以上")
        if req_city:
            req_parts.append(f"要求城市: {req_city}")
        job_requirements = " | ".join(req_parts) if req_parts else "未指定"

        return LLMContext(
            candidate_info=candidate_info,
            matched_content=matched_content,
            candidate_skills=candidate_skills,
            job_requirements=job_requirements,
        )


_context_builder: Optional[ContextBuilder] = None


def get_context_builder() -> ContextBuilder:
    global _context_builder
    if _context_builder is None:
        _context_builder = ContextBuilder()
    return _context_builder
