"""
智能招聘 RAG 推荐系统 - Rerank 重排序模块

使用 BGE-Reranker-v2-m3 API 进行语义重排序
"""

from typing import Any, Dict, List, Optional

import httpx

from src.common.config import get_settings
from src.common.errors import ErrorCode, ExternalServiceError
from src.common.logger import get_logger
from src.recommendation_engine.hybrid_retriever import RetrievalResult

logger = get_logger("reranker")

DEFAULT_TOP_K = 10
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 2


class Reranker:
    """BGE-Reranker 重排序器"""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.embedding.EMBEDDING_API_KEY  # siliconflow key
        self.api_base_url = "https://api.siliconflow.cn/v1"
        self.model = "BAAI/bge-reranker-v2-m3"
        self.timeout = DEFAULT_TIMEOUT
        self._client = httpx.Client(timeout=self.timeout)

    def rerank(
        self,
        results: List[RetrievalResult],
        query_text: str = "",
        top_k: int = DEFAULT_TOP_K,
    ) -> List[RetrievalResult]:
        if not results:
            return []

        # Build documents list from result contents
        documents = []
        for r in results:
            content = r.content
            if isinstance(content, str):
                documents.append(content)
            else:
                documents.append(str(content))

        if not documents:
            return results[:top_k]

        # Call BGE Reranker API
        rerank_scores = self._call_rerank_api(query_text, documents)

        if rerank_scores:
            # Apply rerank scores
            for i, score in enumerate(rerank_scores):
                if i < len(results):
                    results[i].metadata["rerank_score"] = score
                    results[i].metadata["final_score"] = score
                    results[i].score = score

            # Sort by rerank score
            results.sort(key=lambda r: r.metadata.get("final_score", 0), reverse=True)
        else:
            # Fallback: keep original order with original scores as final
            for r in results:
                r.metadata["final_score"] = r.score

        # Update ranks
        for rank, result in enumerate(results[:top_k], start=1):
            result.rank = rank

        logger.info(f"Rerank done: in={len(results)}, out={min(len(results), top_k)}")

        return results[:top_k]

    def _call_rerank_api(self, query: str, documents: List[str]) -> Optional[List[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        }

        for attempt in range(MAX_RETRIES):
            try:
                resp = self._client.post(
                    f"{self.api_base_url}/rerank",
                    headers=headers,
                    json=payload,
                )

                if resp.status_code != 200:
                    logger.warning(f"Rerank API error {resp.status_code}: {resp.text[:200]}")
                    if attempt < MAX_RETRIES - 1:
                        continue
                    return None

                data = resp.json()
                results = data.get("results", [])

                # Build score array indexed by original position
                scores = [0.0] * len(documents)
                for item in results:
                    idx = item.get("index", 0)
                    score = item.get("relevance_score", 0.0)
                    if 0 <= idx < len(scores):
                        scores[idx] = score

                logger.info(f"Rerank API returned {len(results)} scores")
                return scores

            except Exception as e:
                logger.warning(f"Rerank API attempt {attempt+1} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    continue
                return None

        return None


reranker = Reranker()


def get_reranker() -> Reranker:
    return reranker
