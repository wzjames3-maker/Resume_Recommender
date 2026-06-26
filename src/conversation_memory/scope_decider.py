"""
智能招聘 RAG 推荐系统 - 检索范围决策模块

决定是全库检索还是在上次结果中检索
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from src.common.logger import get_logger
from src.intent_router.schemas import CandidateSlot, IntentEnum

logger = get_logger("scope_decider")


class SearchScope(str, Enum):
    """检索范围"""

    FULL = "full"  # 全库检索
    NARROW = "narrow"  # 在上次结果中检索


class ScopeDecision:
    """范围决策结果"""

    def __init__(
        self,
        scope: SearchScope,
        reason: str,
        candidate_ids: Optional[List[str]] = None,
    ):
        self.scope = scope
        self.reason = reason
        self.candidate_ids = candidate_ids or []


class ScopeDecider:
    """范围决策器"""

    def decide(
        self,
        intent: IntentEnum,
        new_slots: CandidateSlot,
        old_slots: Optional[CandidateSlot] = None,
        last_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> ScopeDecision:
        """
        决定检索范围

        Args:
            intent: 意图类型
            new_slots: 新 Slots
            old_slots: 旧 Slots
            last_candidates: 上次推荐的候选人

        Returns:
            ScopeDecision: 范围决策
        """
        # 如果是新搜索，全库检索
        if intent == IntentEnum.RECRUITMENT_SEARCH:
            return ScopeDecision(
                scope=SearchScope.FULL,
                reason="新搜索请求，全库检索",
            )

        # 如果是修正意图
        if intent == IntentEnum.RECRUITMENT_REFINE:
            return self._decide_refine(new_slots, old_slots, last_candidates)

        # 默认全库检索
        return ScopeDecision(
            scope=SearchScope.FULL,
            reason="默认全库检索",
        )

    def _decide_refine(
        self,
        new_slots: CandidateSlot,
        old_slots: Optional[CandidateSlot],
        last_candidates: Optional[List[Dict[str, Any]]],
    ) -> ScopeDecision:
        """
        决定修正意图的检索范围

        Args:
            new_slots: 新 Slots
            old_slots: 旧 Slots
            last_candidates: 上次推荐的候选人

        Returns:
            ScopeDecision: 范围决策
        """
        # 如果没有上次结果，全库检索
        if not last_candidates:
            return ScopeDecision(
                scope=SearchScope.FULL,
                reason="没有上次结果，全库检索",
            )

        # 检查是否只是排序或数量变化
        if self._is_sort_only_change(new_slots, old_slots):
            # 只是排序变化，在上次结果中检索
            candidate_ids = [c.get("resume_id") for c in last_candidates if c.get("resume_id")]
            return ScopeDecision(
                scope=SearchScope.NARROW,
                reason="只是排序或数量变化，在上次结果中检索",
                candidate_ids=candidate_ids,
            )

        # 其他情况，全库检索
        return ScopeDecision(
            scope=SearchScope.FULL,
            reason="条件变化，全库检索",
        )

    def _is_sort_only_change(
        self,
        new_slots: CandidateSlot,
        old_slots: Optional[CandidateSlot],
    ) -> bool:
        """
        检查是否只是排序变化

        Args:
            new_slots: 新 Slots
            old_slots: 旧 Slots

        Returns:
            bool: 是否只是排序变化
        """
        if not old_slots:
            return False

        # 比较主要条件
        new_dict = new_slots.model_dump()
        old_dict = old_slots.model_dump()

        # 检查除了排序相关字段外的其他字段
        for key in new_dict:
            if key in ["sort_by", "order", "count", "page"]:
                continue

            new_val = new_dict[key]
            old_val = old_dict.get(key)

            # 如果新值不为 None 且与旧值不同，则不是只排序变化
            if new_val is not None and new_val != old_val:
                return False

        return True


# 全局范围决策器实例
scope_decider = ScopeDecider()


def get_scope_decider() -> ScopeDecider:
    """获取范围决策器实例"""
    return scope_decider
