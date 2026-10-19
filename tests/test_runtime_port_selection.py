"""节律接线和公开记忆查询必须跟随内核实际选择的端口。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from test_assembly import FakeModel
from test_model_provenance import _config

from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.memory import CONFIG_SPEC as MEMORY_CONFIG
from aurora.configs.rhythm import CONFIG_SPEC as RHYTHM_CONFIG
from src.cadence import Cadence as ConcreteCadence
from src.contracts import EnvironmentEvent, MemorySnapshot
from src.contracts.operation import OperationKind, OperationRequest, OperationStatus
from src.contracts.pkgs.ai import Model
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.cadence import Cadence, RhythmPolicy
from src.contracts.pkgs.console import TerminalConsole
from src.contracts.pkgs.mcp import McpRuntime
from src.contracts.pkgs.memory import MemoryReader
from src.contracts.pkgs.operations import OperationRegistry
from src.contracts.pkgs.world import WorldReader, WorldWriter
from src.contracts.resource import ResourceKey, ResourceRef
from src.kernel import BuiltinSource, compose_managed, module
from src.mcp.runtime import McpRuntime as ConcreteMcpRuntime
from src.rhythm.config import RhythmConfig
from src.runtime import create_runtime, run_runtime

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.contracts.memory import MemoryRequest
    from src.contracts.pkgs.runtime import TerminalDispatcher
    from src.kernel import ModuleContext

_NOW = datetime(2026, 10, 18, tzinfo=UTC)


@pytest.mark.parametrize("invalid_defaults", [False, True])
def test_selected_real_cadence_receives_the_runtime_launcher(
    configured_project: Path, *, invalid_defaults: bool
) -> None:
    """实际替换的节律能唤起认知，默认模组不得把接线留给失选实例。"""
    config = _config(configured_project, "aurora:ai/endpoint/default")
    config = config.with_value(RHYTHM_CONFIG, RhythmConfig(evoke_every=1))
    if invalid_defaults:
        config = config.with_value(
            CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), agent="missing-default", poll_seconds=0)
        )

    @module(
        name="selected_cadence",
        provides=Cadence,
        priority=10,
        requires=(WorldReader, WorldWriter, RhythmPolicy, BotStateStore),
    )
    def selected(context: ModuleContext) -> Cadence:
        """复用真实节律机制，仅由其他模组提供配置与实例。"""
        return ConcreteCadence(
            context.get(WorldReader),
            context.get(WorldWriter),
            policy=context.get(RhythmPolicy),
            state=context.get(BotStateStore),
        )

    async def scenario() -> None:
        """真实装配、启动与唤起全部使用同一个高优先级端口。"""
        model = FakeModel()
        handle = await compose_managed(config, (*BuiltinSource().discover(), selected), instances=((Model, model),))
        runtime = create_runtime(handle.assembly, output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await handle.activate(stop)
            await runtime.submit_event(EnvironmentEvent("signal", "test", "test:world", "changed", _NOW, "环境变化"))
            await handle.assembly.get(Cadence).evaluate_once()
            assert model.requests
        finally:
            await handle.close()

    asyncio.run(scenario())


class SelectedConsole:
    """前台调用必须到达实际选中终端。"""

    def __init__(self) -> None:
        """记录前台启动次数。"""
        self.calls = 0

    async def run(
        self,
        dispatcher: TerminalDispatcher,
        *,
        stop_event: asyncio.Event | None = None,
        readline: Callable[[str], str] | None = None,
        output: Callable[[str], None] = print,
    ) -> None:
        """不读取真实终端，直接完成一次可观察启动。"""
        del dispatcher, readline, output
        self.calls += 1
        assert stop_event is not None
        stop_event.set()


def test_interactive_front_uses_selected_console_port(configured_project: Path) -> None:
    """正式进程入口不能在 Assembly 与前台之间使用两个终端实例。"""
    config = _config(configured_project, "aurora:ai/endpoint/default")
    console = SelectedConsole()

    def eof(prompt: str) -> str:
        """旧实现误走默认终端时也能安全结束，留下调用路径断言失败。"""
        del prompt
        raise EOFError

    runtime = asyncio.run(
        run_runtime(
            config,
            FakeModel(),
            instances=((TerminalConsole, console),),
            readline=eof,
            output=lambda _: None,
        )
    )
    assert runtime.assembly.get(TerminalConsole) is console
    assert console.calls == 1


def test_unselected_mcp_provider_does_not_prepare_default_connections(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """高优先级运行器只在构造阶段提供时，默认准备阶段也必须尊重登记权。"""
    config = _config(configured_project, "aurora:ai/endpoint/default")
    expected = ConcreteMcpRuntime.disabled((), platform_enabled=False)

    async def unexpected(*args: object, **kwargs: object) -> None:
        """失选准备器不允许产生任何连接副作用。"""
        del args, kwargs
        raise AssertionError("失选的 MCP 实现不应准备连接")

    monkeypatch.setattr("src.mcp.module.prepare_mcp", unexpected)

    @module(name="selected_mcp", provides=McpRuntime, priority=10)
    def selected(context: ModuleContext) -> McpRuntime:
        """真实替换对象在构造阶段才可见。"""
        del context
        return expected

    async def scenario() -> None:
        """复用正式 prepare/construct 阶段计划，不提前 seed 运行器。"""
        handle = await compose_managed(
            config, (*BuiltinSource().discover(), selected), instances=((Model, FakeModel()),)
        )
        try:
            assert handle.assembly.get(McpRuntime) is expected
        finally:
            await handle.close()

    asyncio.run(scenario())


class SelectedMemory:
    """可观察的记忆端口，返回来源缺失标记以核对实际调用路径。"""

    def __init__(self) -> None:
        """调用列表用于分别验证认知和公开查询。"""
        self.requests: list[MemoryRequest | None] = []

    async def recall(self, request: MemoryRequest | None = None) -> MemorySnapshot:
        """显式结果标记不依赖默认模型、世界内容或配置。"""
        self.requests.append(request)
        return MemorySnapshot(_NOW, (), missing_refs=("selected-memory",))


def test_engine_and_public_recall_query_use_the_same_selected_memory(configured_project: Path) -> None:
    """失选读取器的无效配置不应阻止替换端口，也不能生成另一套工具行为。"""
    config = _config(configured_project, "aurora:ai/endpoint/default")
    config = config.with_value(MEMORY_CONFIG, replace(config.get(MEMORY_CONFIG), window_minutes=0))
    memory = SelectedMemory()

    @module(name="selected_memory", provides=MemoryReader, priority=10)
    def selected(context: ModuleContext) -> MemoryReader:
        """实际选择的能力由构造器直接提供。"""
        del context
        return memory

    async def scenario() -> None:
        """同一实例先服务引擎，再服务正式领域操作。"""
        handle = await compose_managed(
            config, (*BuiltinSource().discover(), selected), instances=((Model, FakeModel()),)
        )
        runtime = create_runtime(handle.assembly, output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await handle.activate(stop)
            await runtime.run("核对记忆端口")
            before = len(memory.requests)
            assert before > 0
            result = await handle.assembly.get(OperationRegistry).dispatch(
                OperationRequest(
                    "recall-selected",
                    "aurora:bot/default",
                    "test",
                    ResourceRef(ResourceKey.parse("aurora:memory/query/recall"), "1"),
                    OperationKind.QUERY,
                    {"query": "继续核对"},
                )
            )
            assert result.status is OperationStatus.SUCCEEDED
            assert result.data["missing_refs"] == ("selected-memory",)
            assert len(memory.requests) == before + 1
        finally:
            await handle.close()

    asyncio.run(scenario())
