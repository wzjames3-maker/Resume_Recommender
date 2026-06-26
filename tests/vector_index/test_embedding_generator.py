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
        """测试 Dense 转 Sparse"""
        dense = [0.1, 0.0, 0.3, 0.0, 0.5]
        sparse = generator._dense_to_sparse(dense)

        assert 0 in sparse
        assert 2 in sparse
        assert 4 in sparse
        assert 1 not in sparse
        assert 3 not in sparse

    def test_cache_stats(self, generator):
        """测试缓存统计"""
        stats = generator.get_cache_stats()

        assert "cache_size" in stats
        assert "cache_keys" in stats
        assert stats["cache_size"] == 0

    def test_clear_cache(self, generator):
        """测试清除缓存"""
        # 添加一些缓存
        generator._cache["test"] = EmbeddingResult(dense=[], sparse={})

        generator.clear_cache()

        assert len(generator._cache) == 0

    def test_get_embedding_generator(self):
        """测试获取全局实例"""
        generator = get_embedding_generator()
        assert isinstance(generator, EmbeddingGenerator)


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
