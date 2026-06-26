"""
智能招聘 RAG 推荐系统 - 索引管理器测试
"""

import pytest

from src.vector_index.index_manager import (
    CollectionStats,
    IndexManager,
    get_index_manager,
)


@pytest.fixture
def manager():
    """创建索引管理器实例"""
    return IndexManager()


class TestCollectionStats:
    """CollectionStats 测试"""

    def test_create_stats(self):
        """测试创建统计信息"""
        stats = CollectionStats(
            name="resume_chunks",
            row_count=1000,
            index_count=2,
            is_loaded=True,
        )

        assert stats.name == "resume_chunks"
        assert stats.row_count == 1000
        assert stats.index_count == 2
        assert stats.is_loaded is True

    def test_to_dict(self):
        """测试转换为字典"""
        stats = CollectionStats(
            name="resume_chunks",
            row_count=1000,
            index_count=2,
            is_loaded=True,
        )

        data = stats.to_dict()

        assert data["name"] == "resume_chunks"
        assert data["row_count"] == 1000
        assert data["index_count"] == 2
        assert data["is_loaded"] is True


class TestIndexManager:
    """IndexManager 测试"""

    def test_get_index_manager(self):
        """测试获取全局实例"""
        manager = get_index_manager()
        assert isinstance(manager, IndexManager)


class TestIndexManagerIntegration:
    """IndexManager 集成测试（需要 Milvus）"""

    @pytest.mark.skip(reason="需要 Milvus 连接")
    def test_create_collection(self, manager):
        """测试创建 Collection（需要 Milvus）"""
        manager.create_collection()
        assert manager.has_collection()

    @pytest.mark.skip(reason="需要 Milvus 连接")
    def test_create_indexes(self, manager):
        """测试创建索引（需要 Milvus）"""
        manager.create_indexes()

    @pytest.mark.skip(reason="需要 Milvus 连接")
    def test_get_collection_stats(self, manager):
        """测试获取统计信息（需要 Milvus）"""
        stats = manager.get_collection_stats()

        assert stats is not None
        assert stats.name == "resume_chunks"

    @pytest.mark.skip(reason="需要 Milvus 连接")
    def test_drop_collection(self, manager):
        """测试删除 Collection（需要 Milvus）"""
        manager.drop_collection()
        assert not manager.has_collection()
