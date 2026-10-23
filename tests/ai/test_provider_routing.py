"""提供方资源身份与 SDK 协议路由独立，实际请求采用冻结的执行声明。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any, cast

import pytest
from litellm import get_llm_provider

from aurora_bot.ai import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
from aurora_bot.contracts import ChatMessage, ModelRequest
from aurora_bot.contracts.model_binding import ModelBinding, ProviderDefinition
from aurora_bot.contracts.resource import ResourceKey


@pytest.mark.parametrize(
    ("sdk_provider", "remote_model", "base_url"),
    [
        ("deepseek", "deepseek-v4-pro", None),
        ("deepseek", "deepseek-chat", "https://relay.invalid/v1"),
        ("openai", "gpt-4o", None),
        ("xiaomi_mimo", "mimo-v2.5-pro", None),
    ],
)
def test_named_resource_routes_through_explicit_sdk_provider(
    monkeypatch: pytest.MonkeyPatch, sdk_provider: str, remote_model: str, base_url: str | None
) -> None:
    """只替换网络发送，嵌套资源名经过真实 Gateway 和已安装 SDK 的路由解析。"""
    calls: list[dict[str, Any]] = []

    async def call(parameters: dict[str, Any]) -> dict[str, Any]:
        """捕获实际传输参数，配置地址不能在 SDK 边界被忽略。"""
        model, provider, _, parsed_base = get_llm_provider(
            parameters["model"], api_key="offline-placeholder", api_base=parameters.get("api_base")
        )
        assert (model, provider) == (remote_model, sdk_provider)
        if base_url is not None:
            assert parameters["api_base"] == parsed_base == base_url
        calls.append(parameters)
        return {"choices": [{"message": {"role": "assistant", "content": "已核对"}}]}

    monkeypatch.setenv("TEST_ROUTING_KEY", "offline-placeholder")
    provider_key = "lab:ai/provider/accounts/primary"
    endpoint_key = "lab:ai/endpoint/main"
    gateway = LiteLLMModelGateway(
        {provider_key: ProviderEndpoint("litellm", base_url, "TEST_ROUTING_KEY", sdk_provider)},
        {endpoint_key: ModelEndpoint(provider_key, remote_model)},
        caller=call,
        max_attempts=1,
    )
    endpoint = gateway.resolve_endpoint(endpoint_key)
    result = asyncio.run(gateway.complete(ModelRequest(endpoint, (ChatMessage.system("核对环境"),))))
    assert result.content == "已核对"
    assert calls[0]["model"] == f"{sdk_provider}/{remote_model}"
    assert json.loads(endpoint.provider.content)["sdk_provider"] == sdk_provider


def test_sdk_route_is_fixed_in_provider_and_endpoint_versions() -> None:
    """同一个资源名切换协议路由必须产生新版本，改资源名称不能偷偷改 SDK。"""
    provider = ProviderDefinition(
        ResourceKey.parse("lab:ai/provider/accounts/primary"), "litellm", None, "SERVICE_KEY", "deepseek"
    )
    binding = ModelBinding(ResourceKey.parse("lab:ai/endpoint/main"), provider, "remote-model")
    changed = replace(provider, sdk_provider="openai")
    assert provider.ref != changed.ref
    assert replace(binding, provider=changed).ref != binding.ref
    renamed = replace(provider, key=ResourceKey.parse("lab:ai/provider/accounts/backup"))
    assert renamed.sdk_provider == provider.sdk_provider == "deepseek"


def test_omitted_simple_route_and_explicit_route_have_the_same_actual_snapshot() -> None:
    """现有简单名称配置继续工作，显式填写同一个 SDK 前缀不会制造虚假的版本差异。"""
    legacy = ProviderDefinition(ResourceKey.parse("lab:ai/provider/deepseek"), "litellm", None, "SERVICE_KEY")
    assert legacy.sdk_provider == "deepseek"
    assert replace(legacy, sdk_provider="deepseek").ref == legacy.ref
    compatible = ProviderDefinition(
        ResourceKey.parse("lab:ai/provider/accounts/custom"), "openai_compatible", "https://service.invalid/v1", "KEY"
    )
    assert compatible.sdk_provider == "openai"


@pytest.mark.parametrize("route", ["", "deepseek/chat", "lab:deepseek", " deepseek", "deep seek", True])
def test_protocol_route_rejects_nonliteral_or_ambiguous_values(route: object) -> None:
    """协议前缀只能是一个明确的文本值，不能夹带资源路径或被隐式转换。"""
    with pytest.raises(ValueError, match="sdk_provider"):
        ProviderDefinition(ResourceKey.parse("lab:ai/provider/primary"), "litellm", None, "KEY", cast("str", route))


def test_nested_names_need_explicit_sdk_route_and_compatible_adapter_keeps_its_protocol() -> None:
    """无法兼容推导的配置在构造时明确拒绝，不留到网络调用阶段重试。"""
    with pytest.raises(ValueError, match="sdk_provider"):
        ProviderDefinition(ResourceKey.parse("lab:ai/provider/accounts/primary"), "litellm", None, "KEY")
    with pytest.raises(ValueError, match="必须使用 openai"):
        ProviderDefinition(
            ResourceKey.parse("lab:ai/provider/primary"),
            "openai_compatible",
            "https://service.invalid/v1",
            "KEY",
            "deepseek",
        )
