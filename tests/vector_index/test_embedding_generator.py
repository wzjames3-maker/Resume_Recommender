"""
智能招聘 RAG 推荐系统 - Embedding 生成器测试
"""

import pytest

from src.vector_index.embedding_generator import (
    EmbeddingGenerator,
    EmbeddingResult,
    get_embedding_generator,
)


@pytest.fixture
def generator():
    """创建 Embedding 生成器实例"""
    return EmbeddingGenerator()


class TestEmbeddingResult:
    """EmbeddingResult 测试"""

    def test_create_result(self):
        """测试创建结果"""
        result = EmbeddingResult(
            dense=[0.1, 0.2, 0.3],
            sparse={0: 0.1, 1: 0.2},
            token_count=10,
        )

        assert result.dense == [0.1, 0.2, 0.3]
        assert result.sparse == {0: 0.1, 1: 0.2}
        assert result.token_count == 10


class TestEmbeddingGenerator:
    """EmbeddingGenerator 测试"""

    def test_get_cache_key(self, generator):
        """测试生成缓存键"""
        key1 = generator._get_cache_key("测试文本")
        key2 = generator._get_cache_key("测试文本")
        key3 = generator._get_cache_key("其他文本")

        assert key1 == key2  # 相同文本应该有相同的键
        assert key1 != key3  # 不同文本应该有不同的键

    def test_dense_to_sparse(self, generator):
        """Test Dense to Sparse conversion using top-N magnitude"""
        dense = [0.1, 0.0, 0.3, 0.0, 0.5]
        sparse = generator._dense_to_sparse(dense)

        # Sparse should be non-empty
        assert len(sparse) > 0
        assert len(sparse) <= len(dense)
        # All values must be non-negative (Milvus requirement)
        for v in sparse.values():
            assert v >= 0.0
        # Highest magnitude entry (index 4, value 0.5) should be present
        assert 4 in sparse
        assert sparse[4] > 0
class TestEmbeddingGeneratorIntegration:
    """EmbeddingGenerator 集成测试（需要实际 API）"""

    @pytest.mark.skip(reason="需要实际 API 调用")
    def test_generate_embedding(self, generator):
        """测试生成 Embedding（需要实际 API）"""
        result = generator.generate("测试文本")

        assert isinstance(result, EmbeddingResult)
        assert len(result.dense) > 0
        assert len(result.sparse) > 0

    @pytest.mark.skip(reason="需要实际 API 调用")
    def test_batch_generate(self, generator):
        """测试批量生成 Embedding（需要实际 API）"""
        texts = ["文本1", "文本2", "文本3"]
        results = generator.batch_generate(texts)

        assert len(results) == 3
        for result in results:
            assert isinstance(result, EmbeddingResult)
