"""过程定义必须跟随实际选中的运行器，而不是默认模块的配置。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from aurora_bot.contracts.pkgs.agents import AgentCatalog
from aurora_bot.contracts.pkgs.ai import Model
from aurora_bot.contracts.pkgs.artifacts import ArtifactStore
from aurora_bot.contracts.pkgs.bot import BotStateStore
from aurora_bot.contracts.pkgs.engine import CognitionRunner
from aurora_bot.contracts.pkgs.memory import MemoryReader
from aurora_bot.contracts.pkgs.prompt import PromptAssembler
from aurora_bot.contracts.pkgs.resources import ResourceCatalog
from aurora_bot.contracts.pkgs.tools import ToolRegistry
from aurora_bot.contracts.pkgs.world import WorldJournal
from aurora_bot.contracts.process import CognitionProcess
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.contracts.resource_query import ResourceQuery
from aurora_bot.engine import CognitionEngine as ConcreteRunner
from aurora_bot.engine.config import EngineConfig
from aurora_bot.kernel import BuiltinSource, compose_managed, module
from aurora_bot.mcp.config import PlatformsConfig
from aurora_bot.runtime import create_runtime
from aurora_cli import load_config
from aurora_cli.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora_cli.configs.engine import CONFIG_SPEC as ENGINE_CONFIG
from aurora_cli.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.kernel import ModuleContext


def test_selected_runner_process_is_published_and_used_without_loading_default_limits(configured_project: Path) -> None:
    """默认上界不可用时，仍按替换实现的过程成功运行并归档实际定义。"""
    config = load_config(configured_project)
    config = config.with_value(ENGINE_CONFIG, EngineConfig(0, 0, 0))
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    expected = CognitionProcess(max_steps=1, key=ResourceKey.parse("lab:engine/process/selected"))

    @module(
        name="selected_engine",
        provides=CognitionRunner,
        requires=(Model, PromptAssembler, AgentCatalog, ToolRegistry, WorldJournal, MemoryReader, BotStateStore),
        priority=10,
    )
    def custom(context: ModuleContext) -> CognitionRunner:
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
            tree = await runtime.run("按选定过程核对", run_id="selected-process")
            assert tree.status == "completed"
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
