import json

from app.services.outbound_gateway import http_post_json

EMBEDDING_DIM = 1024


class ModelCallError(Exception):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def classify_llm_error(exc: Exception) -> bool:
    """返回 True 表示可重试（超时/限流/暂时网络错误）。"""
    text = str(exc).lower()
    return (
        isinstance(exc, (TimeoutError, ConnectionError))
        or any(k in text for k in ("429", "timeout", "timed out", "temporarily", "rate limit", "503", "502"))
    )


class EmbeddingClient:
    def __init__(self, base_url: str, api_key: str, model: str = "bge-m3"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            data = await http_post_json(url, headers, {"model": self.model, "input": texts})
        except Exception as exc:
            raise ModelCallError(f"embedding 调用失败: {exc}", retryable=classify_llm_error(exc)) from exc
        items = data.get("data", [])
        vecs = [item["embedding"] for item in sorted(items, key=lambda x: x.get("index", 0))]
        for v in vecs:
            if len(v) != EMBEDDING_DIM:
                raise ModelCallError(f"embedding 维度 {len(v)} != {EMBEDDING_DIM}", retryable=False)
        return vecs


class RerankClient:
    """bge-reranker-v2-m3 重排（S-1）：经出站网关，失败按 classify_llm_error 分类。"""

    def __init__(self, base_url: str, api_key: str, model: str = "bge-reranker-v2-m3"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        url = f"{self.base_url}/rerank"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            data = await http_post_json(url, headers, {"model": self.model, "query": query, "documents": documents})
            results = data.get("results") or []
        except Exception as exc:
            raise ModelCallError(f"rerank 调用失败: {exc}", retryable=classify_llm_error(exc)) from exc
        if not results:
            raise ModelCallError("rerank 返回空 results", retryable=False)
        scores = {int(r["index"]): float(r["relevance_score"]) for r in results if "index" in r}
        return [scores[i] for i in range(len(documents)) if i in scores]


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str = "deepseek-chat"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def chat_json(self, system: str, user: str, schema: dict) -> dict:
        """要求模型输出严格 JSON（response_format json_object）。"""
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            data = await http_post_json(url, headers, payload)
        except Exception as exc:
            raise ModelCallError(f"LLM 调用失败: {exc}", retryable=classify_llm_error(exc)) from exc
        content = data["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelCallError("LLM 输出非合法 JSON", retryable=False) from exc