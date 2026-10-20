"""工具接口正文来自实际选中目录，经统一动态资源入口发现和读取。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from test_assembly import FakeModel
from test_tools import EchoTool

from aurora import load_config
from aurora.configs.agents import CONFIG_SPEC as AGENTS_CONFIG
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurorabot.agents.config import AgentsConfig
from aurorabot.contracts.pkgs.ai import Model
from aurorabot.contracts.pkgs.artifacts import ArtifactStore
from aurorabot.contracts.pkgs.resources import ResourceCatalog
from aurorabot.contracts.pkgs.tools import ToolRegistry
from aurorabot.contracts.resource_query import ResourceQuery
from aurorabot.contracts.tool_resource import TOOL_MEDIA_TYPE
from aurorabot.kernel import BuiltinSource, compose_managed, module
from aurorabot.mcp.config import PlatformsConfig
from aurorabot.tools import ToolRegistry as ConcreteRegistry

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from aurorabot.contracts import Tool
    from aurorabot.kernel import ModuleContext


def test_replaced_registry_publishes_only_its_actual_frozen_definitions(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """提供方替换后，失选的内建工具不被构造，也不能被归档成实际接口。"""
    config = load_config(configured_project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    config = config.with_value(
        AGENTS_CONFIG,
        AgentsConfig(tuple(replace(item, tools=(), children=frozenset()) for item in config.get(AGENTS_CONFIG).agents)),
    )
    selected = ConcreteRegistry((EchoTool(),))
    expected = selected.definitions[0]

    def unexpected_builtins(**_kwargs: object) -> tuple[Tool, ...]:
        """不允许在选中目录之外额外构造默认工具。"""
        raise AssertionError("失选工具不应被构造")

    monkeypatch.setattr("aurorabot.tools.module.builtin_tools", unexpected_builtins)

    @module(name="selected_tools", provides=ToolRegistry, priority=10)
    def custom(context: ModuleContext) -> ToolRegistry:
        """为正式装配提供确定的替换目录。"""
        return selected

    async def scenario() -> None:
        """通过实际存储与资源提供者验证目录来源，关闭时回收真实世界连接。"""
        lifecycle = await compose_managed(
            config, (*BuiltinSource().discover(), custom), instances=((Model, FakeModel()),)
        )
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            assembly = lifecycle.assembly
            assert assembly.get(ToolRegistry) is selected
            catalog = assembly.get(ResourceCatalog)
            page = await catalog.browse(ResourceQuery(domain="tool", kind="definition"))
            assert [item.ref for item in page.items] == [expected.ref]
            assert (await catalog.inspect(expected.ref)).metadata["content_verified"] is True
            stored = await assembly.get(ArtifactStore).read(expected.ref)
            assert stored.info.media_type == TOOL_MEDIA_TYPE
            assert stored.content == expected.content
        finally:
            await lifecycle.close()

    asyncio.run(scenario())
