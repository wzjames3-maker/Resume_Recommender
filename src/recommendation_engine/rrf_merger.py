"""
智能招聘 RAG 推荐系统 - RRF 融合排序模块

Reciprocal Rank Fusion 合并 Dense 和 Sparse 检索结果
"""

from typing import Any, Dict, List

from src.common.logger import get_logger

logger = get_logger("rrf_merger")

# 默认 RRF k 参数
DEFAULT_RRF_K = 60


class RRFMerger:
    """RRF 融合排序器"""

    def __init__(self, k: int = DEFAULT_RRF_K):
        """
        初始化 RRF 融合排序器

        Args:
            k: RRF 参数 k
        """
        self.k = k

    def merge(
        self,
        dense_results: List[Dict[str, Any]],
        sparse_results: List[Dict[str, Any]],
        top_k: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        合并 Dense 和 Sparse 检索结果

        Args:
            dense_results: Dense 检索结果
            sparse_results: Sparse 检索结果
            top_k: 返回结果数量

        Returns:
            List[Dict[str, Any]]: 合并后的结果
        """
        # 计算 RRF 分数
        rrf_scores: Dict[str, float] = {}
        result_map: Dict[str, Dict[str, Any]] = {}

        # 处理 Dense 结果
        for rank, result in enumerate(dense_results, start=1):
            chunk_id = result.get("chunk_id")
            if chunk_id:
                rrf_score = 1.0 / (self.k + rank)
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + rrf_score
                result_map[chunk_id] = result

        # 处理 Sparse 结果
        for rank, result in enumerate(sparse_results, start=1):
            chunk_id = result.get("chunk_id")
            if chunk_id:
                rrf_score = 1.0 / (self.k + rank)
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + rrf_score
                result_map[chunk_id] = result

        # 按 RRF 分数排序
        sorted_chunks = sorted(
            rrf_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        # 构建最终结果
        merged_results = []
        for rank, (chunk_id, rrf_score) in enumerate(sorted_chunks[:top_k], start=1):
            result = result_map[chunk_id].copy()
            result["rrf_score"] = rrf_score
            result["rank"] = rank
            merged_results.append(result)

        logger.info(
            f"RRF 融合完成: Dense={len(dense_results)}, Sparse={len(sparse_results)}, "
            f"Merged={len(merged_results)}"
        )

        return merged_results

    def set_k(self, k: int) -> None:
        """
        设置 RRF 参数 k

        Args:
            k: RRF 参数 k
        """
        self.k = k
        logger.info(f"设置 RRF k={k}")


# 全局 RRF 融合排序器实例
rrf_merger = RRFMerger()


def get_rrf_merger() -> RRFMerger:
    """获取 RRF 融合排序器实例"""
    return rrf_merger
