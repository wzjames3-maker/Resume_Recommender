"""
智能招聘 RAG 推荐系统 - 推荐理由生成模块

使用 LLM 生成推荐理由和 Score Breakdown
"""

from typing import Any, Dict, List, Optional

from src.common.logger import get_logger
from src.intent_router.schemas import CandidateSlot
from src.recommendation_engine.hybrid_retriever import RetrievalResult

logger = get_logger("reason_generator")


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
        """转换为字典"""
        return {
            "reason": self.reason,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "score_breakdown": self.score_breakdown,
        }


class ReasonGenerator:
    """推荐理由生成器"""

    def generate(
        self,
        result: RetrievalResult,
        slots: CandidateSlot,
    ) -> ReasonResult:
        """
        生成推荐理由

        Args:
            result: 检索结果
            slots: 候选人属性 Slots

        Returns:
            ReasonResult: 推荐理由结果
        """
        metadata = result.metadata

        # 提取技能匹配信息
        required_skills = slots.skills or []
        candidate_skills = metadata.get("skills", [])

        matched_skills, missing_skills = self._analyze_skills(
            required_skills, candidate_skills,
            job_title=slots.job_title or ""
        )

        # 生成推荐理由
        reason = self._build_reason(result, slots, matched_skills, missing_skills)

        # 构建 Score Breakdown
        score_breakdown = self._build_score_breakdown(result)

        logger.info(f"生成推荐理由: resume_id={result.resume_id}")

        return ReasonResult(
            reason=reason,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            score_breakdown=score_breakdown,
        )

    def _analyze_skills(
        self,
        required_skills: List[str],
        candidate_skills: List[str],
        job_title: str = "",
    ) -> tuple[List[str], List[str]]:
        """
        分析技能匹配

        Args:
            required_skills: 要求的技能
            candidate_skills: 候选人技能

        Returns:
            tuple: (匹配的技能, 缺失的技能)
        """
        if job_title:
            title_keywords = [w for w in job_title.replace("工程师","").replace("开发","").split() if w]
            required_skills = list(required_skills) + title_keywords
        if not required_skills:
            return [], []

        required_set = set(s.lower() for s in required_skills)
        candidate_set = set(s.lower() for s in candidate_skills)

        # 找到匹配的技能
        matched = [
            skill for skill in required_skills
            if skill.lower() in candidate_set
        ]

        # 找到缺失的技能
        missing = [
            skill for skill in required_skills
            if skill.lower() not in candidate_set
        ]

        return matched, missing

    def _build_reason(
        self,
        result: RetrievalResult,
        slots: CandidateSlot,
        matched_skills: List[str],
        missing_skills: List[str],
    ) -> str:
        """
        构建推荐理由

        Args:
            result: 检索结果
            slots: 候选人属性 Slots
            matched_skills: 匹配的技能
            missing_skills: 缺失的技能

        Returns:
            str: 推荐理由
        """
        metadata = result.metadata
        parts = []

        # 基本信息
        candidate_name = metadata.get("candidate_name", "该候选人")
        parts.append(f"{candidate_name}")

        # 技能匹配
        if matched_skills:
            parts.append(f"具备 {', '.join(matched_skills)} 等技能")

        # 工作年限
        years = metadata.get("years_of_experience")
        if years:
            parts.append(f"拥有 {years} 年工作经验")

        # 综合分数
        final_score = metadata.get("final_score", result.score)
        parts.append(f"综合匹配度 {final_score:.1%}")

        # 缺失技能
        if missing_skills:
            parts.append(f"缺少 {', '.join(missing_skills)} 等技能")

        return "，".join(parts) + "。"

    def _build_score_breakdown(self, result: RetrievalResult) -> Dict[str, float]:
        """
        构建 Score Breakdown

        Args:
            result: 检索结果

        Returns:
            Dict[str, float]: 分数明细
        """
        return {
            "semantic_score": result.score,
            "filter_score": result.metadata.get("filter_total_score", 0.0),
            "final_score": result.metadata.get("final_score", result.score),
            "skill_match_score": result.metadata.get("filter_scores", {}).get("skills", 0.0),
            "industry_match_score": result.metadata.get("filter_scores", {}).get("industry", 0.0),
        }


# 全局推荐理由生成器实例
reason_generator = ReasonGenerator()


def get_reason_generator() -> ReasonGenerator:
    """获取推荐理由生成器实例"""
    return reason_generator
