"""真实模型网关的版本在调用前记录，并能跨重启读回历史配置。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from aurora import load_config
from aurora.configs.agents import AGENTS_CONFIG
from aurora.configs.cadence import CADENCE_CONFIG
from aurora.configs.platforms import PLATFORMS_CONFIG
from src.agents.config import AgentsConfig
from src.ai import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
from src.contracts import TreeStatus
from src.contracts.operation import OperationKind, OperationRequest, OperationStatus
from src.contracts.pkgs.operations import OperationRegistry
from src.contracts.resource import ResourceKey, ResourceRef
from src.mcp.config import PlatformsConfig
from src.runtime import compose_runtime

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import pytest

    from aurora import AuroraConfig
    from src.runtime.core import AuroraRuntime


def _config(project: Path, endpoint_name: str) -> AuroraConfig:
    """隔离外部连接和自动认知，让所有原型显式使用待验证端点。"""
    config = load_config(project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    return config.with_value(
        AGENTS_CONFIG,
        AgentsConfig(
            tuple(
                replace(item, model=endpoint_name, tools=(), children=frozenset())
                for item in config.get(AGENTS_CONFIG).agents
            )
        ),
    )


async def _read_definition(runtime: AuroraRuntime, reference: Mapping[str, Any], request_id: str) -> str:
    """历史正文使用正式操作路由读取，不从存储路径或当前配置反推。"""
    request = OperationRequest(
        request_id,
        "aurora:bot/default",
        "test",
        ResourceRef(ResourceKey.parse("aurora:artifacts/query/read"), "1"),
        OperationKind.QUERY,
        {**reference, "encoding": "utf-8", "limit": 16384},
    )
    result = await runtime.assembly.get(OperationRegistry).dispatch(request)
    assert result.status is OperationStatus.SUCCEEDED
    return result.data["text"]


def test_actual_gateway_versions_are_recorded_before_call_and_survive_config_replacement(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SDK 调用之前已有世界事实，重启加载新版本后仍能读取当时的完整配置。"""
    endpoint_name, provider_name = "lab:ai/endpoint/main", "lab:ai/provider/service"
    config = _config(configured_project, endpoint_name)
    monkeypatch.setenv("TEST_MODEL_KEY", "private-not-persisted")

    async def scenario() -> None:
        """使用完整生命周期和真实制品读取路由，只替换外部 SDK 调用。"""
        runtime: AuroraRuntime | None = None
        captured: list[dict[str, Any]] = []

        async def call(parameters: dict[str, Any]) -> dict[str, Any]:
            """调用发生时必须已经能查询到实际请求的确定版本。"""
            assert runtime is not None
            fact = await runtime.world.commit("model-provenance:root:model:0:requested")
            assert fact is not None
            assert fact.data["endpoint_ref"]["key"] == endpoint_name
            assert fact.data["provider_ref"]["key"] == provider_name
            captured.append(parameters)
            return {"choices": [{"message": {"role": "assistant", "content": "核对完成"}}]}

        gateway = LiteLLMModelGateway(
            {provider_name: ProviderEndpoint("openai_compatible", "https://original.invalid/v1", "TEST_MODEL_KEY")},
            {endpoint_name: ModelEndpoint(provider_name, "remote-v1")},
            caller=call,
            max_tokens=1024,
        )
        original = gateway.resolve_endpoint(endpoint_name)
        runtime, lifecycle = await compose_runtime(config, gateway, output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            tree = await runtime.run("核对执行配置", tree_id="model-provenance")
            assert tree.status is TreeStatus.COMPLETED
            assert captured[0]["model"] == "openai/remote-v1"
            assert captured[0]["api_base"] == original.provider.base_url
            assert captured[0]["max_tokens"] == original.max_tokens
        finally:
            await lifecycle.close()

        revised = LiteLLMModelGateway(
            {provider_name: ProviderEndpoint("openai_compatible", "https://revised.invalid/v1", "TEST_MODEL_KEY")},
            {endpoint_name: ModelEndpoint(provider_name, "remote-v2")},
            caller=call,
            max_tokens=2048,
        )
        assert revised.resolve_endpoint(endpoint_name).ref != original.ref
        resumed, handle = await compose_runtime(config, revised, output=lambda _: None)
        try:
            await handle.activate(stop)
            fact = await resumed.world.commit("model-provenance:root:model:0:requested")
            assert fact is not None
            assert fact.data["endpoint_ref"] == {"key": endpoint_name, "revision": original.ref.revision}
            assert fact.data["provider_ref"] == {"key": provider_name, "revision": original.provider.ref.revision}
            for field, definition in (("endpoint_ref", original), ("provider_ref", original.provider)):
                assert fact.data[field] in fact.data["resources"]
                text = await _read_definition(resumed, fact.data[field], f"read-original-{field}")
                assert text.encode("utf-8") == definition.content
                assert "private-not-persisted" not in text
        finally:
            await handle.close()

    asyncio.run(scenario())
