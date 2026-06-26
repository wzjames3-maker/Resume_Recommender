"""
智能招聘 RAG 推荐系统 - VectorIndex 向量索引管理

提供 Milvus Collection 的 CRUD 操作和向量检索功能
"""

from typing import Any, Dict, List, Optional

from pymilvus import (
    AnnSearchRequest,
    Collection,
    DataType,
    FieldSchema,
    RRFRanker,
    utility,
    connections,
)

from src.common.errors import ErrorCode, ExternalServiceError
from src.common.logger import get_logger
from src.vector_index.connection import get_milvus_connection
from src.vector_index.schema import (
    CHUNK_LEVELS,
    COLLECTION_NAME,
    DENSE_DIMENSION,
    DENSE_INDEX_PARAMS,
    HYBRID_SEARCH_PARAMS,
    RRF_K,
    SPARSE_INDEX_PARAMS,
    get_collection_name,
    get_collection_schema,
)

logger = get_logger("vector_index")


class VectorIndex:
    """向量索引管理类"""

    def __init__(self):
        """初始化向量索引管理器"""
        self.connection = get_milvus_connection()
        self._collection: Optional[Collection] = None

    def _ensure_connected(self) -> None:
        """确保已连接 Milvus"""
        if not self.connection.is_connected():
            self.connection.connect()

    def _get_collection(self) -> Collection:
        """获取 Collection 实例"""
        if self._collection is None:
            self._ensure_connected()
            collection_name = get_collection_name()
            self._collection = Collection(collection_name)
        return self._collection

    def create_collection(self) -> None:
        """
        创建 Collection（幂等，已存在则跳过）

        Raises:
            ExternalServiceError: 创建失败
        """
        try:
            self._ensure_connected()
            collection_name = get_collection_name()

            # 检查是否已存在
            if utility.has_collection(collection_name):
                logger.info(f"Collection 已存在: {collection_name}")
                return

            # 获取 Schema
            schema = get_collection_schema()

            # 创建 Collection
            collection = Collection(
                name=collection_name,
                schema=schema,
                using="default",
            )

            logger.info(f"Collection 创建成功: {collection_name}")

            # 刷新引用
            self._collection = collection

        except Exception as e:
            logger.error(f"Collection 创建失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"Collection 创建失败: {str(e)}",
            )

    def create_indexes(self) -> None:
        """
        创建向量索引

        - Dense: HNSW, metric=COSINE
        - Sparse: SPARSE_INVERTED_INDEX, metric=IP

        Raises:
            ExternalServiceError: 索引创建失败
        """
        try:
            collection = self._get_collection()

            # 检查是否已有索引
            if collection.indexes:
                logger.info("索引已存在，跳过创建")
                return

            # 创建 Dense 向量索引
            logger.info("正在创建 Dense 向量索引 (HNSW)...")
            collection.create_index(
                field_name="dense_vector",
                index_params=DENSE_INDEX_PARAMS,
            )

            # 创建 Sparse 向量索引
            logger.info("正在创建 Sparse 向量索引 (SPARSE_INVERTED_INDEX)...")
            collection.create_index(
                field_name="sparse_vector",
                index_params=SPARSE_INDEX_PARAMS,
            )

            logger.info("向量索引创建成功")

        except Exception as e:
            logger.error(f"向量索引创建失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"向量索引创建失败: {str(e)}",
            )

    def insert_chunks(self, chunks: List[Dict[str, Any]]) -> List[int]:
        """
        批量写入 Chunk 向量

        Args:
            chunks: Chunk 数据列表，每个 Chunk 包含:
                - chunk_id: Chunk ID
                - resume_id: 简历 ID
                - chunk_level: Chunk 级别 (small/parent/full)
                - parent_chunk_id: 父 Chunk ID
                - section_type: Section 类型
                - dense_vector: Dense 向量
                - sparse_vector: Sparse 向量 (dict 格式)
                - content: 文本内容
                - metadata: 元数据

        Returns:
            List[int]: Milvus ID 列表

        Raises:
            ExternalServiceError: 写入失败
        """
        try:
            collection = self._get_collection()

            # 准备数据
            data = [
                [chunk["chunk_id"] for chunk in chunks],
                [chunk["resume_id"] for chunk in chunks],
                [chunk["chunk_level"] for chunk in chunks],
                [chunk.get("parent_chunk_id", "") for chunk in chunks],
                [chunk.get("section_type", "") for chunk in chunks],
                [chunk["dense_vector"] for chunk in chunks],
                [chunk["sparse_vector"] for chunk in chunks],
                [chunk["content"] for chunk in chunks],
                [chunk.get("metadata", {}) for chunk in chunks],
            ]

            # 插入数据
            result = collection.insert(data)

            # 刷新数据到存储
            collection.flush()

            logger.info(f"成功写入 {len(chunks)} 个 Chunk 向量")

            return result.primary_keys

        except Exception as e:
            logger.error(f"Chunk 向量写入失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"Chunk 向量写入失败: {str(e)}",
            )

    def hybrid_search_small(
        self,
        query_dense: List[float],
        query_sparse: Dict[int, float],
        top_k: int = 10,
        expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Small Chunk 级别混合检索

        Args:
            query_dense: Dense 查询向量
            query_sparse: Sparse 查询向量 (格式: {index: value})
            top_k: 返回数量
            expr: 标量过滤表达式

        Returns:
            List[Dict[str, Any]]: 检索结果列表

        Raises:
            ExternalServiceError: 检索失败
        """
        try:
            collection = self._get_collection()
            collection.load()

            # 构建查询请求
            # Build search requests (skip empty vectors)
            search_params = []
            if query_dense:
                search_params.append(AnnSearchRequest(
                    data=[query_dense],
                    anns_field="dense_vector",
                    param=HYBRID_SEARCH_PARAMS["dense"],
                    limit=top_k,
                    expr=expr,
                ))
            if query_sparse:
                search_params.append(AnnSearchRequest(
                    data=[query_sparse],
                    anns_field="sparse_vector",
                    param=HYBRID_SEARCH_PARAMS["sparse"],
                    limit=top_k,
                    expr=expr,
                ))
            if not search_params:
                raise ValueError("Both dense and sparse vectors are empty")

            # 执行混合检索
            ranker = RRFRanker(k=RRF_K)
            results = collection.hybrid_search(
                reqs=search_params,
                rerank=ranker,
                limit=top_k,
                output_fields=[
                    "chunk_id",
                    "resume_id",
                    "chunk_level",
                    "parent_chunk_id",
                    "section_type",
                    "content",
                    "metadata",
                ],
            )

            # 格式化结果
            formatted_results = []
            for hits in results:
                for hit in hits:
                    # 兼容 pymilvus v3.0 API
                    entity = hit.entity if hasattr(hit, 'entity') else hit
                    if isinstance(entity, dict):
                        # pymilvus v3.0 返回字典
                        formatted_results.append({
                            "chunk_id": entity.get("chunk_id"),
                            "resume_id": entity.get("resume_id"),
                            "chunk_level": entity.get("chunk_level"),
                            "parent_chunk_id": entity.get("parent_chunk_id"),
                            "section_type": entity.get("section_type"),
                            "content": entity.get("content"),
                            "metadata": entity.get("metadata"),
                            "score": hit.score if hasattr(hit, 'score') else entity.get("distance", 0),
                        })
                    else:
                        # pymilvus v2.x 返回对象
                        formatted_results.append({
                            "chunk_id": entity.get("chunk_id"),
                            "resume_id": entity.get("resume_id"),
                            "chunk_level": entity.get("chunk_level"),
                            "parent_chunk_id": entity.get("parent_chunk_id"),
                            "section_type": entity.get("section_type"),
                            "content": entity.get("content"),
                            "metadata": entity.get("metadata"),
                            "score": hit.score,
                        })

            logger.info(f"Hybrid Search 完成，返回 {len(formatted_results)} 个结果")

            return formatted_results

        except Exception as e:
            logger.error(f"Hybrid Search 失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_001,
                detail=f"Hybrid Search 失败: {str(e)}",
            )

    def retrieve_with_parent(
        self,
        query_dense: List[float],
        query_sparse: Dict[int, float],
        top_k: int = 10,
        expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Small→Big 召回：检索 Small Chunk，返回 Parent Chunk 作为上下文

        Args:
            query_dense: Dense 查询向量
            query_sparse: Sparse 查询向量
            top_k: 返回数量
            expr: 标量过滤表达式

        Returns:
            List[Dict[str, Any]]: 检索结果，包含 small_chunk + parent_chunk + resume_id
        """
        try:
            # 首先检索 Small Chunk
            small_chunks = self.hybrid_search_small(
                query_dense=query_dense,
                query_sparse=query_sparse,
                top_k=top_k,
                expr=expr,
            )

            # 获取所有唯一的 parent_chunk_id
            parent_chunk_ids = list(set(
                chunk["parent_chunk_id"]
                for chunk in small_chunks
                if chunk.get("parent_chunk_id")
            ))

            # 如果没有 parent_chunk_id，直接返回
            if not parent_chunk_ids:
                return small_chunks

            # 查询 Parent Chunk
            collection = self._get_collection()
            collection.load()

            parent_results = collection.query(
                expr=f"chunk_id in {parent_chunk_ids}",
                output_fields=[
                    "chunk_id",
                    "resume_id",
                    "chunk_level",
                    "section_type",
                    "content",
                    "metadata",
                ],
            )

            # 构建 Parent Chunk 映射
            parent_map = {
                parent["chunk_id"]: parent
                for parent in parent_results
            }

            # 组装结果：Small Chunk + Parent Chunk
            results = []
            for small_chunk in small_chunks:
                parent_chunk_id = small_chunk.get("parent_chunk_id")
                parent_chunk = parent_map.get(parent_chunk_id, {}) if parent_chunk_id else {}

                results.append({
                    "small_chunk": small_chunk,
                    "parent_chunk": parent_chunk,
                    "resume_id": small_chunk["resume_id"],
                    "section_type": small_chunk["section_type"],
                    "score": small_chunk["score"],
                })

            logger.info(f"Small→Big 召回完成，返回 {len(results)} 个结果")

            return results

        except Exception as e:
            logger.error(f"Small→Big 召回失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_001,
                detail=f"Small→Big 召回失败: {str(e)}",
            )

    def delete_chunks_by_resume(self, resume_id: str) -> None:
        """
        按 resume_id 删除所有 Chunk

        Args:
            resume_id: 简历 ID

        Raises:
            ExternalServiceError: 删除失败
        """
        try:
            collection = self._get_collection()

            # 删除数据
            expr = f'resume_id == "{resume_id}"'
            collection.delete(expr)

            logger.info(f"成功删除简历 {resume_id} 的所有 Chunk")

        except Exception as e:
            logger.error(f"删除 Chunk 失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"删除 Chunk 失败: {str(e)}",
            )

    def drop_collection(self) -> None:
        """
        删除 Collection（仅测试用）

        Raises:
            ExternalServiceError: 删除失败
        """
        try:
            self._ensure_connected()
            collection_name = get_collection_name()

            if utility.has_collection(collection_name):
                utility.drop_collection(collection_name)
                self._collection = None
                logger.info(f"Collection 删除成功: {collection_name}")
            else:
                logger.warning(f"Collection 不存在: {collection_name}")

        except Exception as e:
            logger.error(f"Collection 删除失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"Collection 删除失败: {str(e)}",
            )

    def has_collection(self) -> bool:
        """
        检查 Collection 是否存在

        Returns:
            bool: 是否存在
        """
        try:
            self._ensure_connected()
            collection_name = get_collection_name()
            return utility.has_collection(collection_name)

        except Exception as e:
            logger.error(f"检查 Collection 失败: {str(e)}")
            return False


# 全局 VectorIndex 实例
vector_index = VectorIndex()


def get_vector_index() -> VectorIndex:
    """获取 VectorIndex 实例"""
    return vector_index
