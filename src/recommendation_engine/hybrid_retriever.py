"""
智能招聘 RAG 推荐系统 - Hybrid Retrieval 混合检索模块

变更 (Tier L): Milvus 标量预过滤 + Resume 级去重
"""

import time
from typing import Any, Dict, List, Optional

from src.common.errors import ErrorCode, ExternalServiceError, ValidationError
from src.common.logger import get_logger
from src.intent_router.schemas import CandidateSlot
from src.recommendation_engine.query_builder import get_query_builder
from src.vector_index.embedding_generator import get_embedding_generator
from src.vector_index.index import get_vector_index

logger = get_logger(__name__)

DEFAULT_TOP_K = 50

EDUCATION_LEVEL_MAP: Dict[str, int] = {
    "高中": 0, "中专": 0, "大专": 1, "本科": 2, "硕士": 3, "博士": 4,
}


class RetrievalResult:
    """检索结果"""

    def __init__(
        self,
        resume_id: str,
        chunk_id: str,
        chunk_level: str,
        parent_chunk_id: Optional[str],
        content: str,
        score: float,
        rank: int,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.resume_id = resume_id
        self.chunk_id = chunk_id
        self.chunk_level = chunk_level
        self.parent_chunk_id = parent_chunk_id
        self.content = content
        self.score = score
        self.rank = rank
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resume_id": self.resume_id,
            "chunk_id": self.chunk_id,
            "chunk_level": self.chunk_level,
            "parent_chunk_id": self.parent_chunk_id,
            "content": self.content,
            "score": self.score,
            "rank": self.rank,
            "metadata": self.metadata,
        }


class HybridRetriever:
    """混合检索器 — 标量预过滤 + Small→Big"""

    def __init__(self):
        self.query_builder = get_query_builder()
        self.embedding_generator = get_embedding_generator()
        self.vector_index = get_vector_index()

    def retrieve(
        self,
        slots: CandidateSlot,
        top_k: int = DEFAULT_TOP_K,
        raw_query: str = "",
    ) -> List[RetrievalResult]:
        start_time = time.time()

        try:
            query_text = self.query_builder.build_query_text_with_raw(slots, raw_query)
            logger.info(f"生成查询 Embedding: {query_text}")
            embedding = self.embedding_generator.generate(query_text)

            filter_expr = self._build_filter_expr(slots)
            logger.info(f"过滤表达式: {filter_expr}")

            raw_results = self.vector_index.retrieve_with_parent(
                query_dense=embedding.dense,
                query_sparse=embedding.sparse,
                top_k=top_k,
                expr=filter_expr,
            )

            final_results = self._aggregate_with_parent(raw_results)
            final_results = self._deduplicate_by_resume(final_results)

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(f"混合检索完成: 结果={len(final_results)}, 耗时={duration_ms}ms")
            return final_results

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"混合检索失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_001,
                detail=f"混合检索失败: {str(e)}",
            )

    def _build_filter_expr(self, slots: CandidateSlot) -> str:
        """构建 Milvus expr 过滤表达式（标量预过滤）"""
        conditions: List[str] = ["chunk_level == 'small'"]

        exp_val = getattr(slots, "experience", None)
        if exp_val is not None:
            op = getattr(slots, "experience_op", None)
            op_str = op.value if hasattr(op, "value") else (op or ">=")
            conditions.append(f"years_of_experience {op_str} {int(exp_val)}")

        edu_val = getattr(slots, "education", None)
        if edu_val is not None:
            edu_str = edu_val.value if hasattr(edu_val, "value") else str(edu_val)
            level = EDUCATION_LEVEL_MAP.get(edu_str, 0)
            if level > 0:
                conditions.append(f"highest_education_level >= {level}")

        city_val = getattr(slots, "city", None)
        if city_val:
            conditions.append(f'city == "{city_val}"')

        gender_val = getattr(slots, "gender", None)
        if gender_val is not None:
            gender_str = gender_val.value if hasattr(gender_val, "value") else str(gender_val)
            conditions.append(f'gender == "{gender_str}"')

        return " && ".join(conditions)

    def _deduplicate_by_resume(
        self, results: List[RetrievalResult],
    ) -> List[RetrievalResult]:
        """Resume 级去重：同 resume_id 只保留最高分"""
        seen: Dict[str, RetrievalResult] = {}
        for r in results:
            if r.resume_id not in seen or r.score > seen[r.resume_id].score:
                seen[r.resume_id] = r
        deduped = sorted(seen.values(), key=lambda x: x.score, reverse=True)
        return deduped

    def _aggregate_with_parent(
        self, results: List[Dict[str, Any]],
    ) -> List[RetrievalResult]:
        final_results = []
        for result in results:
            small = result.get("small_chunk", result)
            parent = result.get("parent_chunk", {})
            parent_content = parent.get("content", "") if parent else ""
            content = parent_content if parent_content else small.get("content", "")

            retrieval_result = RetrievalResult(
                resume_id=result.get("resume_id", small.get("resume_id", "")),
                chunk_id=small.get("chunk_id", ""),
                chunk_level=parent.get("chunk_level", small.get("chunk_level", "small")),
                parent_chunk_id=small.get("parent_chunk_id"),
                content=content,
                score=result.get("score", small.get("score", 0.0)),
                rank=result.get("rank", 0),
                metadata={
                    **(small.get("metadata", {})),
                    "section_type": result.get("section_type", ""),
                },
            )
            final_results.append(retrieval_result)
        return final_results


_hybrid_retriever: Optional[HybridRetriever] = None


def get_hybrid_retriever() -> HybridRetriever:
    global _hybrid_retriever
    if _hybrid_retriever is None:
        _hybrid_retriever = HybridRetriever()
    return _hybrid_retriever
