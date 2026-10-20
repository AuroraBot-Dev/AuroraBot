"""过程定义必须跟随实际选中的运行器，而不是默认模块的配置。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from aurora import load_config
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.engine import CONFIG_SPEC as ENGINE_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurorabot.contracts import TreeStatus
from aurorabot.contracts.pkgs.agents import AgentCatalog
from aurorabot.contracts.pkgs.ai import Model
from aurorabot.contracts.pkgs.artifacts import ArtifactStore
from aurorabot.contracts.pkgs.bot import BotStateStore
from aurorabot.contracts.pkgs.engine import AgentTreeRunner
from aurorabot.contracts.pkgs.memory import MemoryReader
from aurorabot.contracts.pkgs.prompt import PromptAssembler
from aurorabot.contracts.pkgs.resources import ResourceCatalog
from aurorabot.contracts.pkgs.tools import ToolRegistry
from aurorabot.contracts.pkgs.world import WorldJournal
from aurorabot.contracts.process import TreeProcessDefinition
from aurorabot.contracts.resource import ResourceKey
from aurorabot.contracts.resource_query import ResourceQuery
from aurorabot.engine import AgentTreeRunner as ConcreteRunner
from aurorabot.engine.config import EngineConfig
from aurorabot.kernel import BuiltinSource, compose_managed, module
from aurorabot.mcp.config import PlatformsConfig
from aurorabot.runtime import create_runtime
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.kernel import ModuleContext


def test_selected_runner_process_is_published_and_used_without_loading_default_limits(configured_project: Path) -> None:
    """默认上界不可用时，仍按替换实现的过程成功运行并归档实际定义。"""
    config = load_config(configured_project)
    config = config.with_value(ENGINE_CONFIG, EngineConfig(0, 0, 0))
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    expected = TreeProcessDefinition(max_steps=1, key=ResourceKey.parse("lab:engine/process/selected"))

    @module(
        name="selected_engine",
        provides=AgentTreeRunner,
        requires=(Model, PromptAssembler, AgentCatalog, ToolRegistry, WorldJournal, MemoryReader, BotStateStore),
        priority=10,
    )
    def custom(context: ModuleContext) -> AgentTreeRunner:
        """使用真实引擎和世界端口验证替换，不以元数据对象冒充实际执行。"""
        return ConcreteRunner(
            context.get(Model),
            context.get(PromptAssembler),
            context.get(AgentCatalog),
            context.get(ToolRegistry),
            world=context.get(WorldJournal),
            memory=context.get(MemoryReader),
            bot_id=context.get(BotStateStore).bot_id,
            process=expected,
        )

    async def scenario() -> None:
        """资源发现、正文与开始事实都来自同一运行器实例。"""
        lifecycle = await compose_managed(
            config, (*BuiltinSource().discover(), custom), instances=((Model, FakeModel()),)
        )
        runtime = create_runtime(lifecycle.assembly, output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            assert runtime.runner.process_definition is expected
            tree = await runtime.run("按选定过程核对", tree_id="selected-process")
            assert tree.status is TreeStatus.COMPLETED
            page = await lifecycle.assembly.get(ResourceCatalog).browse(ResourceQuery(domain="engine", kind="process"))
            assert [item.ref for item in page.items] == [expected.ref]
            stored = await lifecycle.assembly.get(ArtifactStore).read(expected.ref)
            assert stored.content == expected.content
            started = await runtime.world.commit("selected-process:tree:started")
            assert started is not None
            assert started.data["instance"]["definition"] == {
                "key": str(expected.key),
                "revision": expected.ref.revision,
            }
            instances = await lifecycle.assembly.get(ResourceCatalog).browse(
                ResourceQuery(namespace="lab", domain="engine", kind="instance")
            )
            assert len(instances.items) == 1
            assert instances.items[0].metadata["instance"] == started.data["instance"]
            assert instances.items[0].metadata["state"] == "completed"
        finally:
            await lifecycle.close()

    asyncio.run(scenario())
