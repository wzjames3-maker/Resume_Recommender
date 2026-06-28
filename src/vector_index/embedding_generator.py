"""
智能招聘 RAG 推荐系统 - Embedding 生成模块

使用 BGE-M3 模型生成 Dense + Sparse Embedding
"""

import hashlib
from typing import Any, Dict, List, Optional, Tuple

import httpx

from src.common.config import get_settings
from src.common.errors import ErrorCode, ExternalServiceError
from src.common.logger import get_logger

logger = get_logger("embedding_generator")

# 默认配置
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
BATCH_SIZE = 32


class EmbeddingResult:
    """Embedding 结果"""

    def __init__(
        self,
        dense: List[float],
        sparse: Dict[int, float],
        token_count: int = 0,
    ):
        self.dense = dense
        self.sparse = sparse
        self.token_count = token_count


class EmbeddingGenerator:
    """Embedding 生成器"""

    def __init__(self):
        """初始化 Embedding 生成器"""
        self.settings = get_settings()
        self.api_key = self.settings.embedding.EMBEDDING_API_KEY
        self.api_base_url = self.settings.embedding.EMBEDDING_BASE_URL
        self.model = self.settings.embedding.EMBEDDING_MODEL
        self.dimension = self.settings.embedding.EMBEDDING_DIMENSION
        self.timeout = DEFAULT_TIMEOUT

        self._client = httpx.Client(timeout=self.timeout)

        # 缓存 (TTL + maxsize 限制)
        from cachetools import TTLCache
        self._cache: TTLCache = TTLCache(maxsize=10000, ttl=3600)

    def generate(self, text: str) -> EmbeddingResult:
        """
        生成单个文本的 Embedding

        Args:
            text: 文本内容

        Returns:
            EmbeddingResult: Embedding 结果（Dense + Sparse）

        Raises:
            ExternalServiceError: API 调用失败
        """
        # 检查缓存
        cache_key = self._get_cache_key(text)
        if cache_key in self._cache:
            logger.debug(f"缓存命中: {cache_key[:8]}...")
            return self._cache[cache_key]

        # 调用 API
        result = self._call_api([text])

        if not result:
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_003,
                detail="Embedding 生成失败",
            )

        embedding = result[0]

        # 存入缓存
        self._cache[cache_key] = embedding

        return embedding

    def batch_generate(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        批量生成 Embedding

        Args:
            texts: 文本列表

        Returns:
            List[EmbeddingResult]: Embedding 结果列表

        Raises:
            ExternalServiceError: API 调用失败
        """
        if not texts:
            return []

        # 检查缓存，分离需要调用 API 的文本
        results: List[Optional[EmbeddingResult]] = [None] * len(texts)
        uncached_indices = []
        uncached_texts = []

        for i, text in enumerate(texts):
            cache_key = self._get_cache_key(text)
            if cache_key in self._cache:
                results[i] = self._cache[cache_key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # 批量调用 API
        if uncached_texts:
            logger.info(f"批量生成 Embedding: {len(uncached_texts)} 个文本")

            # 分批处理
            for batch_start in range(0, len(uncached_texts), BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, len(uncached_texts))
                batch_texts = uncached_texts[batch_start:batch_end]
                batch_indices = uncached_indices[batch_start:batch_end]

                batch_results = self._call_api(batch_texts)

                if batch_results:
                    for i, result in zip(batch_indices, batch_results):
                        results[i] = result
                        # 存入缓存
                        cache_key = self._get_cache_key(texts[i])
                        self._cache[cache_key] = result

        # 检查是否有失败的
        for i, result in enumerate(results):
            if result is None:
                raise ExternalServiceError(
                    error_code=ErrorCode.VEC_003,
                    detail=f"Embedding 生成失败: 文本 {i}",
                )

        return results

    def _call_api(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        调用 Embedding API

        Args:
            texts: 文本列表

        Returns:
            List[EmbeddingResult]: Embedding 结果列表
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.post(
                    f"{self.api_base_url}/embeddings",
                    headers=headers,
                    json=payload,
                )

                if response.status_code != 200:
                    error_msg = f"API 返回错误: {response.status_code}"
                    logger.warning(error_msg)

                    if attempt < MAX_RETRIES - 1:
                        continue
                    else:
                        raise ExternalServiceError(
                            error_code=ErrorCode.VEC_003,
                            detail=error_msg,
                        )

                result = response.json()

                # 解析结果
                embeddings = []
                for item in result.get("data", []):
                    dense = item.get("embedding", [])
                    # BGE-M3 返回的是 Dense 向量
                    # Sparse 向量需要单独处理（这里简化为使用 Dense）
                    sparse = self._dense_to_sparse(dense)

                    embeddings.append(EmbeddingResult(
                        dense=dense,
                        sparse=sparse,
                        token_count=result.get("usage", {}).get("total_tokens", 0),
                    ))

                return embeddings

            except httpx.TimeoutException:
                logger.warning(f"API 超时，重试 {attempt + 1}/{MAX_RETRIES}")
                if attempt == MAX_RETRIES - 1:
                    raise ExternalServiceError(
                        error_code=ErrorCode.SYS_004,
                        detail="Embedding API 调用超时",
                    )

            except Exception as e:
                if isinstance(e, ExternalServiceError):
                    raise
                logger.error(f"API 调用异常: {str(e)}")
                if attempt == MAX_RETRIES - 1:
                    raise ExternalServiceError(
                        error_code=ErrorCode.VEC_003,
                        detail=f"Embedding API 调用失败: {str(e)}",
                    )

        return []

    def _dense_to_sparse(self, dense: List[float], top_n: int = 50) -> Dict[int, float]:
        """Generate pseudo-sparse vector from top-N magnitude dense values.
        SiliconFlow does not expose BGE-M3 native sparse, so we extract
        top-N indices by absolute value as a sparse dict."""
        if not dense:
            return {0: 1.0}
        indexed = [(abs(v), i, v) for i, v in enumerate(dense)]
        indexed.sort(reverse=True)
        max_abs = indexed[0][0] if indexed else 1.0
        if max_abs == 0:
            return {0: 1.0}
        result = {}
        for abs_val, idx, val in indexed[:top_n]:
            result[idx] = abs_val / max_abs  # Milvus SPARSE_FLOAT_VECTOR requires non-negative
        return result
    def _get_cache_key(self, text: str) -> str:
        """
        生成缓存键

        Args:
            text: 文本内容

        Returns:
            str: 缓存键
        """
        return hashlib.md5(text.encode()).hexdigest()

    def clear_cache(self) -> None:
        """清除缓存"""
        self._cache.clear()
        logger.info("Embedding 缓存已清除")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计

        Returns:
            Dict: 缓存统计信息
        """
        return {
            "cache_size": len(self._cache),
            "cache_keys": list(self._cache.keys())[:10],  # 只返回前 10 个
        }


# 全局 Embedding 生成器实例
embedding_generator = EmbeddingGenerator()


def get_embedding_generator() -> EmbeddingGenerator:
    """获取 Embedding 生成器实例"""
    return embedding_generator
