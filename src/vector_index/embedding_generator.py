"""
智能招聘 RAG 推荐系统 - Embedding 生成模块

双 Provider 支持：
- Provider=local: FlagEmbedding BGEM3FlagModel 本地推理 Dense + 真实 Sparse
- Provider=siliconflow (或其它 API): 通过 API 获取 Dense + 词频模拟 Sparse

变更 (Tier L): 从纯 API 迁移到 FlagEmbedding 本地推理为主，API 为降级
"""

import hashlib
import re
from typing import Any, Dict, List, Optional

from src.common.config import get_settings
from src.common.logger import get_logger

logger = get_logger(__name__)

BATCH_SIZE = 32
API_TIMEOUT = 30


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
    """Embedding 生成器 — 双 Provider"""

    def __init__(self):
        self._model = None
        self._client = None
        self._provider = None
        self._api_url = None
        self._api_key = None
        self._model_name = None

        from cachetools import TTLCache
        self._cache: TTLCache = TTLCache(maxsize=10000, ttl=3600)

    @property
    def provider(self) -> str:
        if self._provider is None:
            settings = get_settings()
            self._provider = settings.embedding.EMBEDDING_PROVIDER
            self._api_url = settings.embedding.EMBEDDING_BASE_URL
            self._api_key = settings.embedding.EMBEDDING_API_KEY
            self._model_name = settings.embedding.EMBEDDING_MODEL
        return self._provider

    def _get_model(self):
        """懒加载 BGEM3FlagModel (local provider only)"""
        if self._model is None:
            settings = get_settings()
            model_path = settings.embedding.EMBEDDING_MODEL_PATH or None
            logger.info(f"正在加载 FlagEmbedding 模型: {self._model_name}")
            from FlagEmbedding import BGEM3FlagModel
            if model_path:
                self._model = BGEM3FlagModel(
                    model_path,
                    use_fp16=settings.embedding.EMBEDDING_USE_FP16,
                    devices="cpu",
                )
            else:
                self._model = BGEM3FlagModel(
                    self._model_name,
                    use_fp16=settings.embedding.EMBEDDING_USE_FP16,
                    devices="cpu",
                )
            logger.info("FlagEmbedding 模型加载完成 (CPU)")
        return self._model

    def _get_api_client(self):
        """懒加载 httpx Client (api provider only)"""
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=API_TIMEOUT)
        return self._client

    def generate(self, text: str) -> EmbeddingResult:
        cache_key = self._get_cache_key(text)
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = self._encode([text])[0]
        self._cache[cache_key] = result
        return result

    def batch_generate(self, texts: List[str]) -> List[EmbeddingResult]:
        if not texts:
            return []

        results: List[Optional[EmbeddingResult]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        for i, text in enumerate(texts):
            cache_key = self._get_cache_key(text)
            if cache_key in self._cache:
                results[i] = self._cache[cache_key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            logger.info(f"批量生成 Embedding: {len(uncached_texts)} 个文本")
            for batch_start in range(0, len(uncached_texts), BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, len(uncached_texts))
                batch = uncached_texts[batch_start:batch_end]
                batch_indices = uncached_indices[batch_start:batch_end]
                batch_results = self._encode(batch)
                for idx, result in zip(batch_indices, batch_results):
                    results[idx] = result
                    cache_key = self._get_cache_key(texts[idx])
                    self._cache[cache_key] = result

        for i, result in enumerate(results):
            if result is None:
                raise RuntimeError(f"Embedding 生成失败: 文本索引 {i}")

        return results

    def _encode(self, texts: List[str]) -> List[EmbeddingResult]:
        if self.provider == "siliconflow":
            return self._encode_api(texts)
        return self._encode_local(texts)

    def _encode_local(self, texts: List[str]) -> List[EmbeddingResult]:
        model = self._get_model()
        output = model.encode(
            texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
            batch_size=BATCH_SIZE,
        )
        dense_vecs = output["dense_vecs"]
        lexical_weights = output["lexical_weights"]
        results = []
        for i, dense in enumerate(dense_vecs):
            sparse = lexical_weights[i] if i < len(lexical_weights) else {}
            if not sparse:
                logger.warning(f"FlagEmbedding 生成了空的 sparse 向量: text[{i}]")
            results.append(EmbeddingResult(
                dense=dense.tolist(),
                sparse=sparse,
                token_count=len(texts[i]) // 2,
            ))
        return results

    def _encode_api(self, texts: List[str]) -> List[EmbeddingResult]:
        client = self._get_api_client()
        resp = client.post(
            f"{self._api_url.rstrip('/')}/embeddings",
            json={
                "model": self._model_name,
                "input": texts,
                "encoding_format": "float",
            },
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = sorted(data.get("data", []), key=lambda x: x["index"])
        results = []
        for i, item in enumerate(embeddings):
            dense = item["embedding"]
            sparse = self._text_to_sparse(texts[i], len(dense))
            results.append(EmbeddingResult(
                dense=dense,
                sparse=sparse,
                token_count=len(texts[i]) // 2,
            ))
        return results

    @staticmethod
    def _text_to_sparse(text: str, dim: int = 0) -> Dict[int, float]:
        """将文本转为简单的词频 sparse 向量 (API 降级用)"""
        tokens = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z]+', text.lower())
        if not tokens:
            return {0: 0.0}
        freq: Dict[str, float] = {}
        for token in tokens:
            freq[token] = freq.get(token, 0.0) + 1.0
        max_freq = max(freq.values())
        results: Dict[int, float] = {}
        for token, count in freq.items():
            token_id = abs(hash(token)) % 25000
            results[token_id] = count / max_freq
        return results

    def _get_cache_key(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def clear_cache(self) -> None:
        self._cache.clear()
        logger.info("Embedding 缓存已清除")

    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            "cache_size": len(self._cache),
            "cache_keys": list(self._cache.keys())[:10],
        }


_embedding_generator: EmbeddingGenerator | None = None


def get_embedding_generator() -> EmbeddingGenerator:
    global _embedding_generator
    if _embedding_generator is None:
        _embedding_generator = EmbeddingGenerator()
    return _embedding_generator
