"""
智能招聘 RAG 推荐系统 - Slot 提取模块

从用户输入中提取候选人属性 Slots
"""

from typing import Any, Dict, List, Optional

from src.common.logger import get_logger
from src.intent_router.schemas import (
    CandidateSlot,
    ConversationContext,
    IntentEnum,
    IntentResult,
    QuerySlot,
)

logger = get_logger("slot_extractor")


class SlotExtractor:
    """Slot 提取器"""

    def extract_and_merge(
        self,
        intent_result: IntentResult,
        context: Optional[ConversationContext] = None,
    ) -> IntentResult:
        """
        提取并合并 Slots

        Args:
            intent_result: 意图识别结果
            context: 对话上下文

        Returns:
            IntentResult: 合并后的结果
        """
        # 如果没有上下文，直接返回
        if not context or not context.last_query:
            return intent_result

        # 合并 Slots
        merged_candidate_slots = self._merge_candidate_slots(
            intent_result.candidate_slots,
            context.last_query.get("candidate_slots"),
        )

        merged_query_slots = self._merge_query_slots(
            intent_result.query_slots,
            context.last_query.get("query_slots"),
        )

        # 更新结果
        intent_result.candidate_slots = merged_candidate_slots
        intent_result.query_slots = merged_query_slots

        logger.info(f"Slot 合并完成: {intent_result.intent.value}")

        return intent_result

    def _merge_candidate_slots(
        self,
        new_slots: CandidateSlot,
        old_slots_data: Optional[Dict[str, Any]],
    ) -> CandidateSlot:
        """
        合并 CandidateSlot

        Args:
            new_slots: 新提取的 Slots
            old_slots_data: 历史 Slots 数据

        Returns:
            CandidateSlot: 合并后的 Slots
        """
        if not old_slots_data:
            return new_slots

        # 创建历史 Slots
        old_slots = CandidateSlot(**old_slots_data)

        # 合并策略：新值覆盖旧值，None 保留旧值
        merged_data = old_slots.model_dump()

        new_data = new_slots.model_dump()
        for key, value in new_data.items():
            if value is not None:
                merged_data[key] = value

        return CandidateSlot(**merged_data)

    def _merge_query_slots(
        self,
        new_slots: QuerySlot,
        old_slots_data: Optional[Dict[str, Any]],
    ) -> QuerySlot:
        """
        合并 QuerySlot

        Args:
            new_slots: 新提取的 Slots
            old_slots_data: 历史 Slots 数据

        Returns:
            QuerySlot: 合并后的 Slots
        """
        if not old_slots_data:
            return new_slots

        # 创建历史 Slots
        old_slots = QuerySlot(**old_slots_data)

        # 合并策略：使用新值，除非新值是默认值
        merged_data = old_slots.model_dump()

        new_data = new_slots.model_dump()

        # 只覆盖非默认值
        if new_data["count"] != 10:
            merged_data["count"] = new_data["count"]
        if new_data["sort_by"] != "score":
            merged_data["sort_by"] = new_data["sort_by"]
        if new_data["order"] != "desc":
            merged_data["order"] = new_data["order"]
        if new_data["page"] != 1:
            merged_data["page"] = new_data["page"]
        if new_data["top_k"] != 50:
            merged_data["top_k"] = new_data["top_k"]

        return QuerySlot(**merged_data)

    def validate_slots(self, intent_result: IntentResult) -> List[str]:
        """
        验证 Slots 完整性

        Args:
            intent_result: 意图识别结果

        Returns:
            List[str]: 警告信息列表
        """
        warnings = []

        # 根据意图类型验证必需的 Slots
        if intent_result.intent == IntentEnum.RECRUITMENT_SEARCH:
            # 搜索意图至少需要一个条件
            slots = intent_result.candidate_slots
            has_any_slot = (
                slots.job_title
                or slots.skills
                or slots.experience
                or slots.education
                or slots.city
                or slots.industry
                or slots.company
            )

            if not has_any_slot:
                warnings.append("搜索意图缺少候选人条件")

        elif intent_result.intent == IntentEnum.CANDIDATE_LOOKUP:
            # 查看意图需要候选人标识
            slots = intent_result.candidate_slots
            if not slots.job_title and not slots.company:
                warnings.append("查看意图缺少候选人标识")

        return warnings


# 全局 Slot 提取器实例
slot_extractor = SlotExtractor()


def get_slot_extractor() -> SlotExtractor:
    """获取 Slot 提取器实例"""
    return slot_extractor
