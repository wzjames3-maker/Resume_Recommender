"""
智能招聘 RAG 推荐系统 - 元数据过滤模块

硬过滤（Must）和软匹配（Should）
"""

from typing import Any, Dict, List, Optional, Tuple

from src.common.logger import get_logger
from src.intent_router.schemas import CandidateSlot
from src.recommendation_engine.hybrid_retriever import RetrievalResult

logger = get_logger("metadata_filter")

# 默认软匹配权重
DEFAULT_WEIGHTS = {
    "skills": 0.4,
    "industry": 0.3,
    "salary": 0.3,
}


class FilterResult:
    """过滤结果"""

    def __init__(
        self,
        results: List[RetrievalResult],
        filtered_count: int,
        relaxed_constraints: Optional[List[str]] = None,
    ):
        self.results = results
        self.filtered_count = filtered_count
        self.relaxed_constraints = relaxed_constraints or []


class MetadataFilter:
    """元数据过滤器"""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """
        初始化元数据过滤器

        Args:
            weights: 软匹配权重
        """
        self.weights = weights or DEFAULT_WEIGHTS

    def filter(
        self,
        results: List[RetrievalResult],
        slots: CandidateSlot,
    ) -> FilterResult:
        """
        执行过滤

        Args:
            results: 检索结果
            slots: 候选人属性 Slots

        Returns:
            FilterResult: 过滤结果
        """
        if not results:
            return FilterResult(results=[], filtered_count=0)

        # 1. 硬过滤
        filtered_results, filtered_count = self._hard_filter(results, slots)

        # 2. 如果硬过滤后没有结果，尝试 Soft Fallback
        if not filtered_results:
            logger.info("硬过滤后无结果，尝试 Soft Fallback")
            filtered_results, relaxed = self._soft_fallback(results, slots)
            return FilterResult(
                results=filtered_results,
                filtered_count=filtered_count,
                relaxed_constraints=relaxed,
            )

        # 3. 软匹配评分
        scored_results = self._soft_match(filtered_results, slots)

        return FilterResult(
            results=scored_results,
            filtered_count=filtered_count,
        )

    def _hard_filter(
        self,
        results: List[RetrievalResult],
        slots: CandidateSlot,
    ) -> Tuple[List[RetrievalResult], int]:
        """
        硬过滤

        Args:
            results: 检索结果
            slots: 候选人属性 Slots

        Returns:
            Tuple[List[RetrievalResult], int]: (过滤后的结果, 过滤掉的数量)
        """
        filtered = []
        filtered_count = 0

        for result in results:
            metadata = result.metadata

            # 检查城市 (workflow enrich 设置的字段名为 expected_city)
            if slots.city and metadata.get("expected_city"):
                if not self._match_city(slots.city, metadata["expected_city"]):
                    filtered_count += 1
                    continue

            # 检查学历 (workflow enrich 设置的字段名为 highest_education)
            if slots.education and metadata.get("highest_education"):
                if not self._match_education(slots.education.value, metadata["highest_education"]):
                    filtered_count += 1
                    continue

            # 检查工作年限
            if slots.experience is not None and metadata.get("years_of_experience"):
                if not self._match_experience(
                    slots.experience, metadata["years_of_experience"], slots.experience_op
                ):
                    filtered_count += 1
                    continue

            filtered.append(result)

        logger.info(f"硬过滤: 原始={len(results)}, 过滤后={len(filtered)}, 过滤掉={filtered_count}")

        return filtered, filtered_count

    def _soft_fallback(
        self,
        results: List[RetrievalResult],
        slots: CandidateSlot,
    ) -> Tuple[List[RetrievalResult], List[str]]:
        """
        Soft Fallback：逐步放宽硬过滤条件

        Args:
            results: 检索结果
            slots: 候选人属性 Slots

        Returns:
            Tuple[List[RetrievalResult], List[str]]: (结果, 放宽的约束)
        """
        relaxed = []

        # 优先放宽地点 (对 expected_city 字段)
        if slots.city:
            logger.info("放宽地点约束")
            slots.city = None
            relaxed.append("city")

            filtered, _ = self._hard_filter(results, slots)
            if filtered:
                return filtered, relaxed

        # 放宽学历
        if slots.education:
            logger.info("放宽学历约束")
            slots.education = None
            relaxed.append("education")

            filtered, _ = self._hard_filter(results, slots)
            if filtered:
                return filtered, relaxed

        # 放宽年限
        if slots.experience is not None:
            logger.info("放宽年限约束")
            slots.experience = None
            relaxed.append("experience")

            filtered, _ = self._hard_filter(results, slots)
            if filtered:
                return filtered, relaxed

        # 所有条件都放宽后返回原始结果
        return results, relaxed

    def _soft_match(
        self,
        results: List[RetrievalResult],
        slots: CandidateSlot,
    ) -> List[RetrievalResult]:
        """
        软匹配评分

        Args:
            results: 检索结果
            slots: 候选人属性 Slots

        Returns:
            List[RetrievalResult]: 评分后的结果
        """
        for result in results:
            metadata = result.metadata
            filter_scores = {}

            # 技能匹配度 (skills 是字符串列表)
            if slots.skills and metadata.get("skills"):
                filter_scores["skills"] = self._calculate_skill_match(
                    slots.skills, metadata["skills"]
                )
            else:
                filter_scores["skills"] = 0.0

            # 行业匹配度 (从 experience_list 中提取)
            if slots.industry and metadata.get("industry"):
                filter_scores["industry"] = 1.0 if slots.industry == metadata["industry"] else 0.0
            else:
                filter_scores["industry"] = 0.0

            # 薪资匹配度 (workflow enrich 设置的字段名为 expected_salary, 是字符串)
            if slots.salary and metadata.get("expected_salary"):
                filter_scores["salary"] = 0.5  # 字符串无法精确匹配，给默认分
            else:
                filter_scores["salary"] = 0.0

            # 计算加权总分
            total_score = sum(
                filter_scores[dim] * self.weights[dim]
                for dim in filter_scores
            )

            result.metadata["filter_scores"] = filter_scores
            result.metadata["filter_total_score"] = total_score

        # 按软匹配分数排序
        results.sort(
            key=lambda r: r.metadata.get("filter_total_score", 0),
            reverse=True,
        )

        return results

    def _match_city(self, required_city: str, candidate_city: str) -> bool:
        """
        匹配城市

        Args:
            required_city: 要求的城市
            candidate_city: 候选人城市

        Returns:
            bool: 是否匹配
        """
        # 精确匹配或包含匹配
        return required_city in candidate_city or candidate_city in required_city

    def _match_education(self, required: str, candidate: str) -> bool:
        """
        匹配学历

        Args:
            required: 要求的学历
            candidate: 候选人学历

        Returns:
            bool: 是否满足要求
        """
        education_levels = {
            "高中": 1,
            "大专": 2,
            "本科": 3,
            "硕士": 4,
            "博士": 5,
        }

        required_level = education_levels.get(required, 0)
        candidate_level = education_levels.get(candidate, 0)

        return candidate_level >= required_level

    def _match_experience(
        self,
        required: float,
        candidate: float,
        op: Optional[str] = None,
    ) -> bool:
        """
        匹配工作年限

        Args:
            required: 要求的年限
            candidate: 候选人年限
            op: 比较运算符

        Returns:
            bool: 是否满足要求
        """
        if op == ">=":
            return candidate >= required
        elif op == "<=":
            return candidate <= required
        elif op == "=":
            return candidate == required
        else:
            # 默认 >=
            return candidate >= required

    def _calculate_skill_match(
        self,
        required_skills: List[str],
        candidate_skills: List[str],
    ) -> float:
        """
        计算技能匹配度

        Args:
            required_skills: 要求的技能
            candidate_skills: 候选人技能

        Returns:
            float: 匹配度（0-1）
        """
        if not required_skills:
            return 1.0

        # 转换为小写进行比较
        required_set = set(s.lower() for s in required_skills)
        candidate_set = set(s.lower() for s in candidate_skills)

        # 计算交集
        intersection = required_set & candidate_set

        # 计算匹配度（交集 / 要求的技能数）
        return len(intersection) / len(required_set)

    def _calculate_salary_match(
        self,
        required_salary: float,
        salary_range: Dict[str, float],
    ) -> float:
        """
        计算薪资匹配度

        Args:
            required_salary: 要求的薪资
            salary_range: 薪资范围 {"min": xxx, "max": xxx}

        Returns:
            float: 匹配度（0-1）
        """
        min_salary = salary_range.get("min", 0)
        max_salary = salary_range.get("max", float("inf"))

        if min_salary <= required_salary <= max_salary:
            return 1.0
        elif required_salary < min_salary:
            # 期望薪资低于范围
            return max(0, 1 - (min_salary - required_salary) / min_salary)
        else:
            # 期望薪资高于范围
            return max(0, 1 - (required_salary - max_salary) / max_salary)


# 全局元数据过滤器实例
metadata_filter = MetadataFilter()


def get_metadata_filter() -> MetadataFilter:
    """获取元数据过滤器实例"""
    return metadata_filter
