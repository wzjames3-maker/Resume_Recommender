"""
智能招聘 RAG 推荐系统 - 向量索引测试
"""

import random
from typing import Dict, List

import pytest

from src.vector_index.connection import MilvusConnection, get_milvus_connection
from src.vector_index.index import VectorIndex, get_vector_index
from src.vector_index.schema import (
    CHUNK_LEVELS,
    DENSE_DIMENSION,
    SECTION_TYPES,
    get_collection_name,
    get_collection_schema,
)


@pytest.fixture
def milvus_connection():
    """Milvus 连接 fixture"""
    conn = MilvusConnection()
    conn.connect(mode="lite")  # 使用 Lite 模式进行测试
    yield conn
    conn.disconnect()


@pytest.fixture
def vector_index(milvus_connection):
    """VectorIndex fixture"""
    index = VectorIndex()
    yield index
    # 清理
    try:
        index.drop_collection()
    except Exception:
        pass


def generate_random_dense_vector(dim: int = DENSE_DIMENSION) -> List[float]:
    """生成随机 Dense 向量"""
    return [random.random() for _ in range(dim)]


def generate_random_sparse_vector(size: int = 100) -> Dict[int, float]:
    """生成随机 Sparse 向量"""
    indices = random.sample(range(10000), size)
    values = [random.random() for _ in range(size)]
    return dict(zip(indices, values))


def create_test_chunks(resume_id: str, count: int = 3) -> List[Dict]:
    """创建测试 Chunk 数据"""
    chunks = []

    # 创建 Parent Chunk
    parent_chunk = {
        "chunk_id": f"{resume_id}:parent:0",
        "resume_id": resume_id,
        "chunk_level": "parent",
        "parent_chunk_id": "",
        "section_type": "experience",
        "dense_vector": generate_random_dense_vector(),
        "sparse_vector": generate_random_sparse_vector(),
        "content": "工作经历：在字节跳动担任后端工程师",
        "metadata": {"candidate_name": "张三", "city": "北京"},
    }
    chunks.append(parent_chunk)

    # 创建 Small Chunks
    for i in range(count):
        small_chunk = {
            "chunk_id": f"{resume_id}:small:{i}",
            "resume_id": resume_id,
            "chunk_level": "small",
            "parent_chunk_id": f"{resume_id}:parent:0",
            "section_type": "experience",
            "dense_vector": generate_random_dense_vector(),
            "sparse_vector": generate_random_sparse_vector(),
            "content": f"工作内容 {i}",
            "metadata": {"sequence_index": i},
        }
        chunks.append(small_chunk)

    return chunks


class TestMilvusConnection:
    """Milvus 连接测试"""

    def test_connect_lite(self, milvus_connection):
        """测试 Lite 模式连接"""
        assert milvus_connection.is_connected()
        assert milvus_connection.get_mode() == "lite"

    def test_health_check(self, milvus_connection):
        """测试健康检查"""
        assert milvus_connection.health_check() is True

    def test_disconnect(self, milvus_connection):
        """测试断开连接"""
        milvus_connection.disconnect()
        assert milvus_connection.is_connected() is False


class TestCollectionSchema:
    """Collection Schema 测试"""

    def test_get_collection_schema(self):
        """测试获取 Schema"""
        schema = get_collection_schema()
        assert schema is not None

    def test_get_collection_name(self):
        """测试获取 Collection 名称"""
        name = get_collection_name()
        assert "chunks" in name


class TestVectorIndex:
    """VectorIndex 测试"""

    def test_create_collection(self, vector_index):
        """测试创建 Collection"""
        vector_index.create_collection()
        assert vector_index.has_collection()

    def test_create_collection_idempotent(self, vector_index):
        """测试创建 Collection 幂等性"""
        vector_index.create_collection()
        vector_index.create_collection()  # 重复创建不应报错
        assert vector_index.has_collection()

    def test_create_indexes(self, vector_index):
        """测试创建索引"""
        vector_index.create_collection()
        vector_index.create_indexes()

    def test_insert_chunks(self, vector_index):
        """测试插入 Chunk"""
        vector_index.create_collection()
        vector_index.create_indexes()

        # 创建测试数据
        chunks = create_test_chunks("resume-001", count=3)

        # 插入数据
        ids = vector_index.insert_chunks(chunks)
        assert len(ids) == 4  # 1 parent + 3 small

    def test_hybrid_search_small(self, vector_index):
        """测试 Small Chunk 混合检索"""
        vector_index.create_collection()
        vector_index.create_indexes()

        # 插入测试数据
        chunks = create_test_chunks("resume-001", count=3)
        vector_index.insert_chunks(chunks)

        # 执行检索
        query_dense = generate_random_dense_vector()
        query_sparse = generate_random_sparse_vector()

        results = vector_index.hybrid_search_small(
            query_dense=query_dense,
            query_sparse=query_sparse,
            top_k=5,
        )

        # 验证结果
        assert isinstance(results, list)
        assert len(results) > 0

        for result in results:
            assert "chunk_id" in result
            assert "resume_id" in result
            assert "chunk_level" in result
            assert "content" in result
            assert "score" in result

    def test_retrieve_with_parent(self, vector_index):
        """测试 Small→Big 召回"""
        vector_index.create_collection()
        vector_index.create_indexes()

        # 插入测试数据
        chunks = create_test_chunks("resume-001", count=3)
        vector_index.insert_chunks(chunks)

        # 执行检索
        query_dense = generate_random_dense_vector()
        query_sparse = generate_random_sparse_vector()

        results = vector_index.retrieve_with_parent(
            query_dense=query_dense,
            query_sparse=query_sparse,
            top_k=5,
        )

        # 验证结果
        assert isinstance(results, list)
        assert len(results) > 0

        for result in results:
            assert "small_chunk" in result
            assert "parent_chunk" in result
            assert "resume_id" in result

    def test_delete_chunks_by_resume(self, vector_index):
        """测试删除 Chunk"""
        vector_index.create_collection()
        vector_index.create_indexes()

        # 插入测试数据
        chunks = create_test_chunks("resume-001", count=3)
        vector_index.insert_chunks(chunks)

        # 删除数据
        vector_index.delete_chunks_by_resume("resume-001")

    def test_drop_collection(self, vector_index):
        """测试删除 Collection"""
        vector_index.create_collection()
        assert vector_index.has_collection()

        vector_index.drop_collection()
        assert not vector_index.has_collection()
