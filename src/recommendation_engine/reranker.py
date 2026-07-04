"""
智能招聘 RAG 推荐系统 - Rerank 重排序模块

变更 (Tier L): 加权融合（非覆盖式替换）
final_score = RERANK_WEIGHT * rerank_score + RETRIEVAL_WEIGHT * norm_retrieval_score
"""

from typing import Any, Dict, List, Optional

import httpx

from src.common.config import get_settings
from src.common.logger import get_logger
from src.recommendation_engine.hybrid_retriever import RetrievalResult

logger = get_logger(__name__)

RERANK_WEIGHT = 0.7
RETRIEVAL_WEIGHT = 0.3
DEFAULT_TOP_K = 10
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 2


class Reranker:
    """BGE-Reranker 重排序器 — 加权融合"""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.reranker.RERANKER_API_KEY
        self.api_base_url = settings.reranker.RERANKER_BASE_URL
        self.model = settings.reranker.RERANKER_MODEL
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

        documents = [self._build_document(r) for r in results]

        rerank_scores = self._call_rerank_api(query_text, documents)

        if rerank_scores:
            retrieval_scores = [r.score for r in results]
            max_ret = max(retrieval_scores) if retrieval_scores else 1.0

            for i, (r, rerank) in enumerate(zip(results, rerank_scores)):
                norm_retrieval = r.score / max_ret if max_ret > 0 else 0.0
                final = RERANK_WEIGHT * rerank + RETRIEVAL_WEIGHT * norm_retrieval
                r.metadata["rerank_score"] = rerank
                r.metadata["retrieval_score"] = r.score
                r.metadata["final_score"] = final
                r.score = final
        else:
            for r in results:
                r.metadata["final_score"] = r.score
            results.sort(key=lambda r: r.score, reverse=True)

        # Sort by final score and update ranks
        results.sort(key=lambda r: r.metadata.get("final_score", r.score), reverse=True)
        for rank, r in enumerate(results[:top_k], start=1):
            r.rank = rank

        logger.info(f"Rerank done: in={len(results)}, out={min(len(results), top_k)}")
        return results[:top_k]

    def _build_document(self, result: RetrievalResult) -> str:
        """构建结构化 document 文本供 Reranker 使用"""
        m = result.metadata
        parts = []
        name = m.get("candidate_name", "")
        title = m.get("current_title", m.get("title", ""))
        org = m.get("organization", m.get("current_company", ""))
        exp_yrs = m.get("years_of_experience", 0)
        skills = m.get("skills_normalized", [])

        if name:
            parts.append(name)
        if title:
            parts.append(title)
        if org:
            parts.append(org)
        if exp_yrs:
            parts.append(f"{exp_yrs}年经验")
        if skills:
            parts.append("技能: " + ", ".join(skills[:10]))
        parts.append(f"内容: {result.content}")
        return " | ".join(parts)

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
                    logger.warning(f"Rerank API error {resp.status_code}")
                    if attempt < MAX_RETRIES - 1:
                        continue
                    return None

                data = resp.json()
                items = data.get("results", [])
                scores = [0.0] * len(documents)
                for item in items:
                    idx = item.get("index", 0)
                    score = item.get("relevance_score", 0.0)
                    if 0 <= idx < len(scores):
                        scores[idx] = score

                logger.info(f"Rerank API returned {len(items)} scores")
                return scores

            except Exception as e:
                logger.warning(f"Rerank API attempt {attempt+1} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    continue
                return None

        return None


_reranker: Optional[Reranker] = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker
