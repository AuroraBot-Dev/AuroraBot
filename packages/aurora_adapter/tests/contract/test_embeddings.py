"""模拟 HTTP 验证向量协议、索引顺序及错误脱敏，不访问供应商。"""

import asyncio
import json

import httpx
import pytest
from aurora_adapter.model import ModelConfig, ModelError, ModelProtocolError
from aurora_adapter.model.config import resolve_model
from aurora_adapter.model.litellm import LiteLLMClient
from aurora_adapter.model.plugin import plugin
from aurora_adapter.model.response import normalize_vectors
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import register_plugins


@pytest.mark.parametrize("provider", ["openai", "voyage"])
def test_embedding_transport_orders_vectors_and_sanitizes_errors(provider):
    async def scenario():
        seen = []

        def handle(request):
            seen.append(request)
            assert str(request.url) == "https://embedding.test/v1/embeddings"
            assert request.headers["authorization"] == "Bearer runtime-secret"
            assert json.loads(request.content) == {
                "model": "small",
                "input": ["茶", "咖啡"],
                "encoding_format": "float",
            }
            if len(seen) == 3:
                return httpx.Response(307, headers={"Location": "https://redirect.test/embeddings"})
            if len(seen) == 2:
                return httpx.Response(429, text="runtime-secret 私密记忆")
            return httpx.Response(
                200, json={"data": [{"index": 1, "embedding": [0, 3]}, {"index": 0, "embedding": [2, 0]}]}
            )

        client = LiteLLMClient(
            kind="embedding",
            config=ModelConfig("small", "https://embedding.test/v1", provider=provider),
            api_key="runtime-secret",
            transport=httpx.MockTransport(handle),
        )
        try:
            assert await client.embed(["茶", "咖啡"]) == [[1, 0], [0, 1]]
            with pytest.raises(ModelError) as failure:
                await client.embed(["茶", "咖啡"])
            assert "runtime-secret" not in str(failure.value) and "私密记忆" not in str(failure.value)
            assert len(seen) == 2
            with pytest.raises(ModelError):
                await client.embed(["茶", "咖啡"])
            assert len(seen) == 3
        finally:
            await client.aclose()
        with pytest.raises(ModelError, match="关闭"):
            await client.embed(["茶"])

    asyncio.run(scenario())


def test_embedding_contract_rejects_invalid_vectors_and_chat_adapters():
    for value, count in (([[0, 0]], 1), ([[float("nan")]], 1), ([[True]], 1), ([[1, 2], [1]], 2), ([[1]], 2)):
        with pytest.raises(ModelProtocolError):
            normalize_vectors(value, count)
    registry = bootstrap()
    register_plugins(registry, (plugin(),))
    profiles = {"vector": {"adapter": "org.aurora.adapter:adapters/model/litellm/embedding", "model": "small"}}
    bindings = {"memory": "vector"}
    resolved = resolve_model(registry, profiles, bindings, "memory", kind="embedding")
    assert resolved.config.model == "small"
    with pytest.raises(TypeError, match="需要 chat"):
        resolve_model(registry, profiles, bindings, "memory")
    profiles["vector"]["adapter"] = "org.aurora.adapter:adapters/model/litellm/chat"
    with pytest.raises(TypeError, match="需要 embedding"):
        resolve_model(registry, profiles, bindings, "memory", kind="embedding")
