"""
智能招聘 RAG 推荐系统 - 查询文本构建模块

从 Slots 构建检索查询文本
"""

from typing import List, Optional

from src.common.errors import ErrorCode, ValidationError
from src.common.logger import get_logger
from src.intent_router.schemas import CandidateSlot

logger = get_logger("query_builder")

# 停用词列表
STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就",
    "不", "人", "都", "一", "一个", "上", "也", "很",
    "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这", "他", "她", "它",
}


class QueryBuilder:
    """查询文本构建器"""

    def build_query_text(self, slots: CandidateSlot) -> str:
        """
        从 Slots 构建查询文本

        Args:
            slots: 候选人属性 Slots

        Returns:
            str: 查询文本

        Raises:
            ValidationError: Slots 全部为空或拼接结果为空
        """
        # 提取查询关键词
        keywords = self._extract_keywords(slots)

        # 空查询守卫
        if not keywords:
            raise ValidationError(
                error_code=ErrorCode.SYS_001,
                detail="查询条件为空，请提供至少一个搜索条件",
            )

        # 拼接查询文本
        query_text = " ".join(keywords)

        # 去停用词
        query_text = self._remove_stop_words(query_text)

        # 再次检查是否为空
        if not query_text.strip():
            raise ValidationError(
                error_code=ErrorCode.SYS_001,
                detail="查询条件为空，请提供至少一个搜索条件",
            )

        logger.info(f"构建查询文本: {query_text}")

        return query_text

    def _extract_keywords(self, slots: CandidateSlot) -> List[str]:
        """
        从 Slots 提取关键词

        Args:
            slots: 候选人属性 Slots

        Returns:
            List[str]: 关键词列表
        """
        keywords = []

        # 提取职位
        if slots.job_title:
            keywords.append(slots.job_title)

        # 提取技能
        if slots.skills:
            keywords.extend(slots.skills)

        # 提取工作年限
        if slots.experience is not None:
            experience_value = int(slots.experience) if slots.experience == int(slots.experience) else slots.experience
            keywords.append(f"{experience_value}年以上工作经验")

        # 提取行业
        if slots.industry:
            keywords.append(slots.industry)

        # 提取城市
        if slots.city:
            keywords.append(slots.city)

        # 提取学历
        if slots.education:
            keywords.append(slots.education.value)

        # 提取公司
        if slots.company:
            keywords.append(slots.company)

        # 提取学校
        if slots.school:
            keywords.append(slots.school)

        return keywords

    def _remove_stop_words(self, text: str) -> str:
        """
        去停用词

        Args:
            text: 原始文本

        Returns:
            str: 去停用词后的文本
        """
        words = text.split()
        filtered_words = [word for word in words if word not in STOP_WORDS]
        return " ".join(filtered_words)

    def build_empty_query_error(self) -> ValidationError:
        """
        构建空查询错误

        Returns:
            ValidationError: 空查询错误
        """
        return ValidationError(
            error_code=ErrorCode.SYS_001,
            detail="查询条件为空，请提供至少一个搜索条件",
        )



    def build_query_text_with_raw(self, slots, raw_query: str = "") -> str:
        """Build query text from slots + original user query for better semantics"""
        keywords = self._extract_keywords(slots)
        # Include the raw user query for richer semantics
        if raw_query and raw_query.strip():
            clean_raw = raw_query.strip()
            # Deduplicate: only add raw query if it's not already covered by keywords
            existing_text = " ".join(keywords)
            if clean_raw != existing_text:
                # Check if raw query is substantially different from keywords
                # Avoid adding if raw query is just a subset of keywords
                keywords_set = set(k.lower() for k in keywords)
                raw_words = set(w.lower() for w in clean_raw.split() if len(w) > 1)
                # If most raw words are already in keywords, don't add
                if raw_words and not raw_words.issubset(keywords_set):
                    keywords.insert(0, clean_raw)
        if not keywords:
            raise ValidationError(
                error_code=ErrorCode.SYS_001,
                detail="查询条件为空",
            )
        query_text = " ".join(keywords)
        query_text = self._remove_stop_words(query_text)
        if not query_text.strip():
            raise ValidationError(
                error_code=ErrorCode.SYS_001,
                detail="查询条件为空",
            )
        logger.info(f"构建查询文本(含原文): {query_text}")
        return query_text

# 全局查询构建器实例
query_builder = QueryBuilder()


def get_query_builder() -> QueryBuilder:
    """获取查询构建器实例"""
    return query_builder
