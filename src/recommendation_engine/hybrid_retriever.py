"""
智能招聘 RAG 推荐系统 - Hybrid Retrieval 混合检索模块

整合 Dense 检索、Sparse 检索和 RRF 融合
"""

import time
from typing import Any, Dict, List, Optional

from src.common.errors import ErrorCode, ExternalServiceError, ValidationError
from src.common.logger import get_logger
from src.intent_router.schemas import CandidateSlot
from src.recommendation_engine.query_builder import get_query_builder
from src.recommendation_engine.rrf_merger import get_rrf_merger
from src.vector_index.embedding_generator import get_embedding_generator
from src.vector_index.index import get_vector_index

logger = get_logger("hybrid_retriever")

# 默认配置
DEFAULT_TOP_K = 50


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
        """转换为字典"""
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
    """混合检索器"""

    def __init__(self):
        """初始化混合检索器"""
        self.query_builder = get_query_builder()
        self.embedding_generator = get_embedding_generator()
        self.vector_index = get_vector_index()
        self.rrf_merger = get_rrf_merger()

    def retrieve(
        self,
        slots: CandidateSlot,
        top_k: int = DEFAULT_TOP_K,
        expr: Optional[str] = None,
        raw_query: str = "",
    ) -> List[RetrievalResult]:
        """
        执行混合检索

        Args:
            slots: 候选人属性 Slots
            top_k: 返回结果数量
            expr: 额外的过滤表达式

        Returns:
            List[RetrievalResult]: 检索结果列表

        Raises:
            ValidationError: 查询条件为空
            ExternalServiceError: 检索失败
        """
        start_time = time.time()

        try:
            # 1. 构建查询文本
            query_text = self.query_builder.build_query_text_with_raw(slots, raw_query)

            # 2. 生成 Embedding
            logger.info(f"生成查询 Embedding: {query_text}")
            embedding = self.embedding_generator.generate(query_text)

            # 3. 构建过滤表达式（限定 Small Chunk）
            filter_expr = "chunk_level == 'small'"
            if expr:
                filter_expr = f"({filter_expr}) && ({expr})"

            # 4. Small→Big 检索+聚合 (单次调用完成)
            logger.info("执行 Hybrid Search + Small→Big")
            raw_results = self.vector_index.retrieve_with_parent(
                query_dense=embedding.dense,
                query_sparse=embedding.sparse,
                top_k=top_k,
                expr=filter_expr,
            )

            # 5. 构建 RetrievalResult 列表
            final_results = self._aggregate_with_parent(raw_results)

            # 计算耗时
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"混合检索完成: 结果={len(final_results)}, 耗时={duration_ms}ms"
            )

            return final_results

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"混合检索失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_001,
                detail=f"混合检索失败: {str(e)}",
            )

    def _dense_search(
        self,
        dense_vector: List[float],
        top_k: int,
        expr: str,
    ) -> List[Dict[str, Any]]:
        """
        Dense 向量检索

        Args:
            dense_vector: Dense 查询向量
            top_k: 返回数量
            expr: 过滤表达式

        Returns:
            List[Dict[str, Any]]: Dense 检索结果
        """
        try:
            results = self.vector_index.hybrid_search_small(
                query_dense=dense_vector,
                query_sparse={},  # 只使用 Dense
                top_k=top_k,
                expr=expr,
            )

            return results

        except Exception as e:
            logger.error(f"Dense 检索失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_001,
                detail=f"Dense 检索失败: {str(e)}",
            )

    def _sparse_search(
        self,
        sparse_vector: Dict[int, float],
        top_k: int,
        expr: str,
    ) -> List[Dict[str, Any]]:
        """
        Sparse 向量检索

        Args:
            sparse_vector: Sparse 查询向量
            top_k: 返回数量
            expr: 过滤表达式

        Returns:
            List[Dict[str, Any]]: Sparse 检索结果
        """
        try:
            results = self.vector_index.hybrid_search_small(
                query_dense=[],  # 只使用 Sparse
                query_sparse=sparse_vector,
                top_k=top_k,
                expr=expr,
            )

            return results

        except Exception as e:
            logger.error(f"Sparse 检索失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_001,
                detail=f"Sparse 检索失败: {str(e)}",
            )

    def _aggregate_with_parent(
        self,
        results: List[Dict[str, Any]],
    ) -> List[RetrievalResult]:
        """
        Small→Big 上下文聚合：获取 Parent Chunk 的真实内容

        Args:
            results: Small Chunk 检索结果 (from retrieve_with_parent)

        Returns:
            List[RetrievalResult]: 聚合后的结果（含 parent chunk 内容）
        """
        final_results = []

        for result in results:
            # retrieve_with_parent returns {small_chunk, parent_chunk, resume_id, section_type, score}
            small = result.get("small_chunk", result)
            parent = result.get("parent_chunk", {})

            # Use parent chunk content if available, otherwise fall back to small chunk
            parent_content = parent.get("content", "") if parent else ""
            content = parent_content if parent_content else small.get("content", "")

            retrieval_result = RetrievalResult(
                resume_id=result.get("resume_id", small.get("resume_id", "")),
                chunk_id=small.get("chunk_id", ""),
                chunk_level=parent.get("chunk_level", small.get("chunk_level", "small")),
                parent_chunk_id=small.get("parent_chunk_id"),
                content=content,
                score=result.get("score", small.get("rrf_score", 0.0)),
                rank=result.get("rank", 0),
                metadata={
                    **(small.get("metadata", {})),
                    "section_type": result.get("section_type", ""),
                },
            )

            final_results.append(retrieval_result)

        return final_results


# 全局混合检索器实例
hybrid_retriever = HybridRetriever()


def get_hybrid_retriever() -> HybridRetriever:
    """获取混合检索器实例"""
    return hybrid_retriever
