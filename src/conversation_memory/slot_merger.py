"""
智能招聘 RAG 推荐系统 - Slot 合并模块

Slot 合并（增量/覆盖/重置）
"""

from enum import Enum
from typing import Any, Dict, Optional

from src.common.logger import get_logger
from src.intent_router.schemas import CandidateSlot, QuerySlot

logger = get_logger("slot_merger")


class MergeStrategy(str, Enum):
    """合并策略"""

    INCREMENTAL = "incremental"  # 增量合并
    OVERRIDE = "override"  # 覆盖
    RESET = "reset"  # 重置


class SlotMerger:
    """Slot 合并器"""

    def merge_candidate_slots(
        self,
        new_slots: CandidateSlot,
        old_slots: Optional[CandidateSlot],
        strategy: MergeStrategy = MergeStrategy.INCREMENTAL,
    ) -> CandidateSlot:
        """
        合并 CandidateSlot

        Args:
            new_slots: 新 Slots
            old_slots: 旧 Slots
            strategy: 合并策略

        Returns:
            CandidateSlot: 合并后的 Slots
        """
        if strategy == MergeStrategy.RESET:
            return new_slots

        if not old_slots:
            return new_slots

        if strategy == MergeStrategy.OVERRIDE:
            return self._override_merge(new_slots, old_slots)

        # 增量合并
        return self._incremental_merge(new_slots, old_slots)

    def merge_query_slots(
        self,
        new_slots: QuerySlot,
        old_slots: Optional[QuerySlot],
        strategy: MergeStrategy = MergeStrategy.INCREMENTAL,
    ) -> QuerySlot:
        """
        合并 QuerySlot

        Args:
            new_slots: 新 Slots
            old_slots: 旧 Slots
            strategy: 合并策略

        Returns:
            QuerySlot: 合并后的 Slots
        """
        if strategy == MergeStrategy.RESET:
            return new_slots

        if not old_slots:
            return new_slots

        if strategy == MergeStrategy.OVERRIDE:
            return new_slots

        # 增量合并
        return self._incremental_merge_query(new_slots, old_slots)

    def _incremental_merge(
        self,
        new_slots: CandidateSlot,
        old_slots: CandidateSlot,
    ) -> CandidateSlot:
        """
        增量合并 CandidateSlot

        Args:
            new_slots: 新 Slots
            old_slots: 旧 Slots

        Returns:
            CandidateSlot: 合并后的 Slots
        """
        # 转换为字典
        old_dict = old_slots.model_dump()
        new_dict = new_slots.model_dump()

        # 合并：新值覆盖旧值，None 保留旧值
        merged = old_dict.copy()
        for key, value in new_dict.items():
            if value is not None:
                merged[key] = value

        return CandidateSlot(**merged)

    def _override_merge(
        self,
        new_slots: CandidateSlot,
        old_slots: CandidateSlot,
    ) -> CandidateSlot:
        """
        覆盖合并 CandidateSlot

        Args:
            new_slots: 新 Slots
            old_slots: 旧 Slots

        Returns:
            CandidateSlot: 合并后的 Slots
        """
        # 覆盖：直接使用新值
        return new_slots

    def _incremental_merge_query(
        self,
        new_slots: QuerySlot,
        old_slots: QuerySlot,
    ) -> QuerySlot:
        """
        增量合并 QuerySlot

        Args:
            new_slots: 新 Slots
            old_slots: 旧 Slots

        Returns:
            QuerySlot: 合并后的 Slots
        """
        # 转换为字典
        old_dict = old_slots.model_dump()
        new_dict = new_slots.model_dump()

        # 合并：只覆盖非默认值
        merged = old_dict.copy()

        defaults = QuerySlot().model_dump()
        for key, value in new_dict.items():
            if value != defaults.get(key):
                merged[key] = value

        return QuerySlot(**merged)


# 全局 Slot 合并器实例
slot_merger = SlotMerger()


def get_slot_merger() -> SlotMerger:
    """获取 Slot 合并器实例"""
    return slot_merger
