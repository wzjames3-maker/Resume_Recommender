"""
智能招聘 RAG 推荐系统 - 索引管理模块

管理 Milvus Collection 和索引
"""

from typing import Any, Dict, Optional

from src.common.errors import ErrorCode, ExternalServiceError
from src.common.logger import get_logger
from src.vector_index.connection import get_milvus_connection
from src.vector_index.index import get_vector_index

logger = get_logger("index_manager")


class CollectionStats:
    """Collection 统计信息"""

    def __init__(
        self,
        name: str,
        row_count: int,
        index_count: int,
        is_loaded: bool,
    ):
        self.name = name
        self.row_count = row_count
        self.index_count = index_count
        self.is_loaded = is_loaded

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "row_count": self.row_count,
            "index_count": self.index_count,
            "is_loaded": self.is_loaded,
        }


class IndexManager:
    """索引管理器"""

    def __init__(self):
        """初始化索引管理器"""
        self.connection = get_milvus_connection()
        self.vector_index = get_vector_index()

    def create_collection(self) -> None:
        """
        创建 Collection

        Raises:
            ExternalServiceError: 创建失败
        """
        try:
            logger.info("创建 Collection")
            self.vector_index.create_collection()
            logger.info("Collection 创建成功")

        except Exception as e:
            logger.error(f"Collection 创建失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"Collection 创建失败: {str(e)}",
            )

    def create_indexes(self) -> None:
        """
        创建索引

        Raises:
            ExternalServiceError: 索引创建失败
        """
        try:
            logger.info("创建索引")
            self.vector_index.create_indexes()
            logger.info("索引创建成功")

        except Exception as e:
            logger.error(f"索引创建失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"索引创建失败: {str(e)}",
            )

    def drop_collection(self) -> None:
        """
        删除 Collection

        Raises:
            ExternalServiceError: 删除失败
        """
        try:
            logger.info("删除 Collection")
            self.vector_index.drop_collection()
            logger.info("Collection 删除成功")

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
        return self.vector_index.has_collection()

    def get_collection_stats(self) -> Optional[CollectionStats]:
        """
        获取 Collection 统计信息

        Returns:
            Optional[CollectionStats]: 统计信息，不存在返回 None
        """
        try:
            if not self.has_collection():
                return None

            from pymilvus import Collection, utility

            collection_name = self.vector_index._get_collection_name()
            collection = Collection(collection_name)

            # 获取统计信息
            stats = collection.num_entities
            indexes = collection.indexes
            is_loaded = utility.load_state(collection_name)

            return CollectionStats(
                name=collection_name,
                row_count=stats,
                index_count=len(indexes),
                is_loaded=is_loaded == "Loaded",
            )

        except Exception as e:
            logger.error(f"获取 Collection 统计失败: {str(e)}")
            return None

    def rebuild_indexes(self) -> None:
        """
        重建索引

        Raises:
            ExternalServiceError: 重建失败
        """
        try:
            logger.info("重建索引")

            # 删除现有索引
            from pymilvus import Collection

            collection_name = self.vector_index._get_collection_name()
            collection = Collection(collection_name)

            for index in collection.indexes:
                collection.drop_index(index.field_name)

            # 重新创建索引
            self.vector_index.create_indexes()

            logger.info("索引重建成功")

        except Exception as e:
            logger.error(f"索引重建失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"索引重建失败: {str(e)}",
            )

    def load_collection(self) -> None:
        """
        加载 Collection 到内存

        Raises:
            ExternalServiceError: 加载失败
        """
        try:
            logger.info("加载 Collection")

            from pymilvus import Collection

            collection_name = self.vector_index._get_collection_name()
            collection = Collection(collection_name)
            collection.load()

            logger.info("Collection 加载成功")

        except Exception as e:
            logger.error(f"Collection 加载失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"Collection 加载失败: {str(e)}",
            )

    def release_collection(self) -> None:
        """
        释放 Collection（从内存中移除）

        Raises:
            ExternalServiceError: 释放失败
        """
        try:
            logger.info("释放 Collection")

            from pymilvus import Collection

            collection_name = self.vector_index._get_collection_name()
            collection = Collection(collection_name)
            collection.release()

            logger.info("Collection 释放成功")

        except Exception as e:
            logger.error(f"Collection 释放失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"Collection 释放失败: {str(e)}",
            )


# 全局索引管理器实例
index_manager = IndexManager()


def get_index_manager() -> IndexManager:
    """获取索引管理器实例"""
    return index_manager
