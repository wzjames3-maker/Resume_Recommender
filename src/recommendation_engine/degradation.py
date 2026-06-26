"""
智能招聘 RAG 推荐系统 - 降级策略和去重模块

推荐降级策略和结果去重
"""

from typing import Any, Dict, List, Optional, Set

from src.common.logger import get_logger
from src.recommendation_engine.hybrid_retriever import RetrievalResult

logger = get_logger("degradation")


class DegradationResult:
    """降级结果"""

    def __init__(
        self,
        results: List[RetrievalResult],
        degradation_level: int = 0,
        degradation_reason: Optional[str] = None,
    ):
        self.results = results
        self.degradation_level = degradation_level
        self.degradation_reason = degradation_reason


class Deduplicator:
    """去重器"""

    def deduplicate(
        self,
        results: List[RetrievalResult],
    ) -> List[RetrievalResult]:
        """
        去重

        Args:
            results: 检索结果

        Returns:
            List[RetrievalResult]: 去重后的结果
        """
        seen_resume_ids: Set[str] = set()
        deduplicated = []

        for result in results:
            resume_id = result.resume_id

            if resume_id not in seen_resume_ids:
                seen_resume_ids.add(resume_id)
                deduplicated.append(result)
            else:
                logger.debug(f"去重: 跳过重复的 resume_id={resume_id}")

        logger.info(f"去重: 输入={len(results)}, 输出={len(deduplicated)}")

        return deduplicated


class DegradationStrategy:
    """降级策略"""

    def __init__(self):
        """初始化降级策略"""
        self.deduplicator = Deduplicator()

    def apply(
        self,
        results: List[RetrievalResult],
        min_results: int = 5,
    ) -> DegradationResult:
        """
        应用降级策略

        Args:
            results: 检索结果
            min_results: 最小结果数量

        Returns:
            DegradationResult: 降级结果
        """
        # 1. 去重
        deduplicated = self.deduplicator.deduplicate(results)

        # 2. 检查是否需要降级
        if len(deduplicated) >= min_results:
            return DegradationResult(
                results=deduplicated,
                degradation_level=0,
            )

        # 3. 降级策略
        return self._apply_degradation(deduplicated, min_results)

    def _apply_degradation(
        self,
        results: List[RetrievalResult],
        min_results: int,
    ) -> DegradationResult:
        """
        应用降级策略

        Args:
            results: 检索结果
            min_results: 最小结果数量

        Returns:
            DegradationResult: 降级结果
        """
        # 降级级别 1: 放宽分数阈值
        if len(results) > 0:
            logger.info("降级级别 1: 返回所有有结果的候选人")
            return DegradationResult(
                results=results,
                degradation_level=1,
                degradation_reason="结果不足，返回所有匹配的候选人",
            )

        # 降级级别 2: 返回空结果
        logger.warning("降级级别 2: 无匹配结果")
        return DegradationResult(
            results=[],
            degradation_level=2,
            degradation_reason="未找到符合条件的候选人",
        )


# 全局去重器实例
deduplicator = Deduplicator()

# 全局降级策略实例
degradation_strategy = DegradationStrategy()


def get_deduplicator() -> Deduplicator:
    """获取去重器实例"""
    return deduplicator


def get_degradation_strategy() -> DegradationStrategy:
    """获取降级策略实例"""
    return degradation_strategy
