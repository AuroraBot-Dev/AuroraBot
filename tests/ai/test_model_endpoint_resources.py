"""端点和提供方的身份、冻结配置与实际调用策略保持一致。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest

from aurorabot.ai import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
from aurorabot.ai.config import EndpointConfig, ProviderConfig
from aurorabot.contracts import ChatMessage, ModelRequest
from aurorabot.contracts.model_binding import ModelBinding, ProviderDefinition
from aurorabot.contracts.resource import ResourceKey
from tests.support.model import fake_endpoint


@pytest.mark.parametrize("name", ["default", "lab:ai/provider/default", "lab:memory/model/tgn"])
def test_model_request_rejects_incomplete_or_wrong_kind_endpoint(name: str) -> None:
    """每次推理必须明确选择端点，其他资源不能被当作模型名字。"""
    with pytest.raises(ValueError, match="模型资源身份"):
        ModelRequest(fake_endpoint(name), (ChatMessage.system("主体身份"),))


def test_configuration_uses_separate_endpoint_and_provider_kinds() -> None:
    """配置引用使用完整身份，远端模型名称不被当作本地资源重写。"""
    provider = ProviderConfig("lab:ai/provider/service", "litellm", "SERVICE_KEY")
    endpoint = EndpointConfig("lab:ai/endpoint/main", provider.name, "vendor/opaque-model")
    assert endpoint.model == "vendor/opaque-model"
    with pytest.raises(ValueError, match="模型资源身份"):
        EndpointConfig("lab:ai/endpoint/main", "service", endpoint.model)
    with pytest.raises(ValueError, match="模型资源身份"):
        ProviderConfig(endpoint.name, "litellm", "SERVICE_KEY")


def _binding() -> ModelBinding:
    """为版本和策略验证提供完整、无密钥值的端点快照。"""
    provider = ProviderDefinition(
        ResourceKey.parse("lab:ai/provider/service"), "openai_compatible", "https://example.invalid/v1", "SERVICE_KEY"
    )
    return ModelBinding(ResourceKey.parse("lab:ai/endpoint/main"), provider, "vendor/model")


def test_endpoint_version_covers_provider_and_every_execution_setting() -> None:
    """端点版本固定提供方版本与全部策略，不能只对远端模型名计算摘要。"""
    original = _binding()
    assert original.ref.revision == hashlib.sha256(original.content).hexdigest()
    assert original.provider.ref.revision == hashlib.sha256(original.provider.content).hexdigest()
    assert json.loads(original.content)["provider"] == {
        "key": str(original.provider.key),
        "revision": original.provider.ref.revision,
    }
    for changed in (
        replace(original, model="another-model"),
        replace(original, timeout_seconds=10),
        replace(original, max_attempts=3),
        replace(original, total_timeout_seconds=90),
        replace(original, max_tokens=1024),
        replace(original, provider=replace(original.provider, adapter="litellm")),
        replace(original, provider=replace(original.provider, base_url="https://another.invalid")),
        replace(original, provider=replace(original.provider, secret_env="OTHER_KEY")),
    ):
        assert changed.ref != original.ref
    assert replace(original, timeout_seconds=30).ref == replace(original, timeout_seconds=30.0).ref


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf"), True])
def test_binding_requires_finite_positive_deadlines(timeout: float) -> None:
    """无法形成实际截止时间的策略不能被发布为有效执行配置。"""
    with pytest.raises(ValueError, match="有限正数"):
        replace(_binding(), timeout_seconds=timeout)


def test_gateway_uses_the_same_frozen_binding_for_route_and_request_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """外部字典修改不改变已编译端点，密钥值只在实际调用时解析。"""
    captured: list[dict[str, Any]] = []

    async def call(parameters: dict[str, Any]) -> dict[str, Any]:
        """捕获真实网关构造的 SDK 参数，不发起外部请求。"""
        captured.append(parameters)
        return {"choices": [{"message": {"role": "assistant", "content": "核对完成"}}]}

    provider_name, endpoint_name = "lab:ai/provider/service", "lab:ai/endpoint/main"
    providers = {provider_name: ProviderEndpoint("openai_compatible", "https://example.invalid/v1", "SERVICE_KEY")}
    endpoints = {endpoint_name: ModelEndpoint(provider_name, "vendor/model")}
    gateway = LiteLLMModelGateway(providers, endpoints, caller=call, timeout_seconds=0.1, max_tokens=1024)
    binding = gateway.endpoints[0]
    assert binding.provider is gateway.providers[0]
    providers[provider_name] = ProviderEndpoint("openai_compatible", "https://another.invalid", "OTHER_KEY")
    endpoints[endpoint_name] = ModelEndpoint(provider_name, "another-model")
    monkeypatch.setenv("SERVICE_KEY", "private-live-value")
    response = asyncio.run(
        gateway.complete(ModelRequest(gateway.resolve_endpoint(endpoint_name), (ChatMessage.system("主体身份"),)))
    )
    assert response.content == "核对完成"
    assert gateway.endpoints[0] is binding
    assert captured[0]["api_base"] == binding.provider.base_url
    assert captured[0]["model"] == "openai/vendor/model"
    assert captured[0]["timeout"] == binding.timeout_seconds
    assert captured[0]["max_tokens"] == binding.max_tokens
    assert captured[0]["api_key"] == "private-live-value"
    assert b"private-live-value" not in binding.content + binding.provider.content


def test_gateway_rejects_a_same_name_request_with_another_binding_version() -> None:
    """同名路由改变后必须显式重建请求，不能在网关内悄悄换成新配置。"""
    provider_name, endpoint_name = "lab:ai/provider/service", "lab:ai/endpoint/main"
    providers = {provider_name: ProviderEndpoint("litellm", None, "SERVICE_KEY")}
    original = LiteLLMModelGateway(providers, {endpoint_name: ModelEndpoint(provider_name, "original-model")})
    revised = LiteLLMModelGateway(providers, {endpoint_name: ModelEndpoint(provider_name, "another-model")})
    request = ModelRequest(original.resolve_endpoint(endpoint_name), (ChatMessage.system("主体身份"),))
    with pytest.raises(ValueError, match="端点版本与当前网关不一致"):
        asyncio.run(revised.complete(request))
