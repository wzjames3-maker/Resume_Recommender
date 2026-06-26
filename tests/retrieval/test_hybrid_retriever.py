"""
智能招聘 RAG 推荐系统 - 混合检索测试
"""

import pytest

from src.intent_router.schemas import CandidateSlot
from src.recommendation_engine.hybrid_retriever import (
    HybridRetriever,
    RetrievalResult,
    get_hybrid_retriever,
)
from src.recommendation_engine.rrf_merger import RRFMerger, get_rrf_merger


@pytest.fixture
def retriever():
    """创建混合检索器实例"""
    return HybridRetriever()


@pytest.fixture
def merger():
    """创建 RRF 融合排序器实例"""
    return RRFMerger()


class TestRetrievalResult:
    """RetrievalResult 测试"""

    def test_create_result(self):
        """测试创建结果"""
        result = RetrievalResult(
            resume_id="R001",
            chunk_id="R001:small:0",
            chunk_level="small",
            parent_chunk_id="R001:parent:0",
            content="测试内容",
            score=0.9,
            rank=1,
        )

        assert result.resume_id == "R001"
        assert result.chunk_id == "R001:small:0"
        assert result.score == 0.9
        assert result.rank == 1

    def test_to_dict(self):
        """测试转换为字典"""
        result = RetrievalResult(
            resume_id="R001",
            chunk_id="R001:small:0",
            chunk_level="small",
            parent_chunk_id="R001:parent:0",
            content="测试内容",
            score=0.9,
            rank=1,
        )

        data = result.to_dict()

        assert data["resume_id"] == "R001"
        assert data["chunk_id"] == "R001:small:0"
        assert data["score"] == 0.9


class TestRRFMerger:
    """RRFMerger 测试"""

    def test_merge_basic(self, merger):
        """测试基本合并"""
        dense_results = [
            {"chunk_id": "chunk-1", "content": "内容1"},
            {"chunk_id": "chunk-2", "content": "内容2"},
        ]

        sparse_results = [
            {"chunk_id": "chunk-2", "content": "内容2"},
            {"chunk_id": "chunk-3", "content": "内容3"},
        ]

        merged = merger.merge(dense_results, sparse_results)

        assert len(merged) == 3
        # chunk-2 应该排在最前面（两个结果都包含）
        assert merged[0]["chunk_id"] == "chunk-2"

    def test_merge_with_rrf_score(self, merger):
        """测试 RRF 分数计算"""
        dense_results = [
            {"chunk_id": "chunk-1", "content": "内容1"},
        ]

        sparse_results = [
            {"chunk_id": "chunk-1", "content": "内容1"},
        ]

        merged = merger.merge(dense_results, sparse_results)

        # chunk-1 在两个结果中都排第 1，RRF 分数应该是 2 * 1/(60+1)
        expected_score = 2 * (1.0 / (60 + 1))
        assert abs(merged[0]["rrf_score"] - expected_score) < 0.001

    def test_merge_top_k(self, merger):
        """测试 top_k 限制"""
        dense_results = [
            {"chunk_id": f"chunk-{i}", "content": f"内容{i}"}
            for i in range(100)
        ]

        sparse_results = []

        merged = merger.merge(dense_results, sparse_results, top_k=10)

        assert len(merged) == 10

    def test_set_k(self, merger):
        """测试设置 k 参数"""
        merger.set_k(100)
        assert merger.k == 100

    def test_get_rrf_merger(self):
        """测试获取全局实例"""
        merger = get_rrf_merger()
        assert isinstance(merger, RRFMerger)


class TestHybridRetriever:
    """HybridRetriever 测试"""

    def test_get_hybrid_retriever(self):
        """测试获取全局实例"""
        retriever = get_hybrid_retriever()
        assert isinstance(retriever, HybridRetriever)


class TestHybridRetrieverIntegration:
    """HybridRetriever 集成测试（需要 Milvus）"""

    @pytest.mark.skip(reason="需要 Milvus 和 Embedding API")
    def test_retrieve(self, retriever):
        """测试混合检索（需要 Milvus）"""
        slots = CandidateSlot(
            job_title="Java工程师",
            experience=3,
            city="北京",
        )

        results = retriever.retrieve(slots, top_k=10)

        assert len(results) > 0
        for result in results:
            assert isinstance(result, RetrievalResult)
            assert result.resume_id
            assert result.chunk_id
            assert result.score > 0
