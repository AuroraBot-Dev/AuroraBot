"""真实配置装配采用独立 SDK 路由，并在重启后保留原始调用依据。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from litellm import get_llm_provider

from aurora.configs.endpoints import CONFIG_SPEC as ENDPOINTS_CONFIG
from aurorabot.ai import gateway
from aurorabot.ai.config import EndpointConfig, EndpointsConfig
from aurorabot.contracts import TreeStatus
from aurorabot.contracts.pkgs.ai import Model
from aurorabot.runtime import compose_runtime
from tests.ai.endpoint_support import _config, _read_definition

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from aurora import AuroraConfig

_PROVIDER = "lab:ai/provider/accounts/primary"
_ENDPOINT = "lab:ai/endpoint/main"
_BASE_URL = "https://relay.invalid/v1"


def _configured(project: Path, sdk_provider: str, model: str) -> AuroraConfig:
    """路由来自实际 TOML 字段，默认 AI 模组负责编译执行快照。"""
    (project / "config" / "providers.toml").write_text(
        f'[[provider]]\nname = "{_PROVIDER}"\nadapter = "litellm"\n'
        f'sdk_provider = "{sdk_provider}"\nbase_url = "{_BASE_URL}"\nsecret_env = "TEST_ROUTING_KEY"\n',
        encoding="utf-8",
    )
    return _config(project, _ENDPOINT).with_value(
        ENDPOINTS_CONFIG, EndpointsConfig((EndpointConfig(_ENDPOINT, _PROVIDER, model),))
    )


def test_toml_sdk_route_drives_actual_default_gateway_and_survives_restart(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只替换 SDK 网络发送，实际调用、世界版本和历史正文使用同一份配置。"""
    captured: list[tuple[str, str, str]] = []

    async def complete(**parameters: object) -> dict[str, object]:
        """已安装 SDK 的真实解析器验证传输路由和地址。"""
        model, base = parameters["model"], parameters.get("api_base")
        assert isinstance(model, str) and isinstance(base, str)
        _, provider, _, _ = get_llm_provider(model, api_base=base, api_key="offline-placeholder")
        captured.append((model, provider, base))
        return {"choices": [{"message": {"role": "assistant", "content": "核对完成"}}]}

    monkeypatch.setattr(gateway.litellm, "acompletion", complete)
    monkeypatch.setenv("TEST_ROUTING_KEY", "offline-placeholder")

    async def scenario() -> None:
        """重启替换配置后，从旧世界引用读取原先采用的 SDK 路由。"""
        config = _configured(configured_project, "deepseek", "deepseek-chat")
        runtime, handle = await compose_runtime(config, output=lambda _: None)
        original = runtime.assembly.get(Model).resolve_endpoint(_ENDPOINT)
        stop = asyncio.Event()
        stop.set()
        try:
            await handle.activate(stop)
            result = await runtime.run("核对当前配置", tree_id="configured-route")
            assert result.status is TreeStatus.COMPLETED
            assert captured == [("deepseek/deepseek-chat", "deepseek", _BASE_URL)]
            assert original.provider.sdk_provider == "deepseek"
        finally:
            await handle.close()
        revised = _configured(configured_project, "openai", "gpt-4o")
        resumed, lifecycle = await compose_runtime(revised, output=lambda _: None)
        try:
            await lifecycle.activate(stop)
            current = resumed.assembly.get(Model).resolve_endpoint(_ENDPOINT)
            assert current.provider.sdk_provider == "openai"
            assert current.ref != original.ref
            fact = await resumed.world.commit("configured-route:root:model:0:requested")
            assert fact is not None
            assert fact.data["provider_ref"]["revision"] == original.provider.ref.revision
            text = await _read_definition(resumed, fact.data["provider_ref"], "read-configured-route")
            assert text.encode() == original.provider.content
            assert json.loads(text)["sdk_provider"] == "deepseek"
            assert "offline-placeholder" not in text
        finally:
            await lifecycle.close()

    asyncio.run(scenario())
