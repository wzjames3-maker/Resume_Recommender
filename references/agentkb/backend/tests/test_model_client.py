import pytest

from app.services.model_client import (
    EmbeddingClient,
    LLMClient,
    ModelCallError,
    classify_llm_error,
)


def _patch_post(monkeypatch, payload: dict):
    """将 outbound_gateway.http_post_json 替换为返回固定 payload。"""
    async def fake_post(url, headers, json, timeout=60.0):
        return payload
    monkeypatch.setattr("app.services.model_client.http_post_json", fake_post)


@pytest.mark.asyncio
async def test_embedding_client_returns_1024_dim(monkeypatch):
    _patch_post(monkeypatch, {"data": [{"index": 0, "embedding": [0.1] * 1024},
                                       {"index": 1, "embedding": [0.2] * 1024}]})
    client = EmbeddingClient(base_url="https://api.example.com/v1", api_key="sk-test")
    vecs = await client.embed(["你好", "世界"])
    assert len(vecs) == 2
    assert all(len(v) == 1024 for v in vecs)


@pytest.mark.asyncio
async def test_embedding_dimension_mismatch_is_not_retryable(monkeypatch):
    _patch_post(monkeypatch, {"data": [{"index": 0, "embedding": [0.1] * 512}]})
    client = EmbeddingClient(base_url="https://api.example.com/v1", api_key="sk-test")
    with pytest.raises(ModelCallError) as exc:
        await client.embed(["x"])
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_llm_client_json_call(monkeypatch):
    _patch_post(monkeypatch, {"choices": [{"message": {"content": '{"name": "张三"}'}}]})
    client = LLMClient(base_url="https://api.deepseek.com/v1", api_key="sk-test")
    out = await client.chat_json(system="你是解析器", user="解析简历", schema={"type": "object"})
    assert out == {"name": "张三"}


def test_classify_llm_error():
    assert classify_llm_error(TimeoutError()) is True        # 可重试
    assert classify_llm_error(ValueError("schema")) is False  # 不可重试