import pytest

from app.services.model_client import ModelCallError, RerankClient


def _patch_post(monkeypatch, payload: dict):
    async def fake_post(url, headers, json, timeout=60.0):
        return payload
    monkeypatch.setattr("app.services.model_client.http_post_json", fake_post)


@pytest.mark.asyncio
async def test_rerank_returns_scores_for_documents(monkeypatch):
    _patch_post(monkeypatch, {"results": [{"index": 0, "relevance_score": 0.9},
                                           {"index": 1, "relevance_score": 0.2}]})
    client = RerankClient(base_url="https://api.example.com/v1", api_key="sk-test", model="bge-reranker-v2-m3")
    scores = await client.rerank("找 Java 后端", ["Python 简历", "Java 支付系统"])
    assert len(scores) == 2
    assert scores[0] > scores[1]


@pytest.mark.asyncio
async def test_rerank_missing_results_is_not_retryable(monkeypatch):
    _patch_post(monkeypatch, {"results": []})
    client = RerankClient(base_url="https://api.example.com/v1", api_key="sk-test")
    with pytest.raises(ModelCallError) as exc:
        await client.rerank("q", ["d"])
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_rerank_empty_documents_returns_empty():
    client = RerankClient(base_url="https://api.example.com/v1", api_key="sk-test")
    assert await client.rerank("q", []) == []