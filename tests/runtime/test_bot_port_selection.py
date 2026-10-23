"""主体状态、公开命令与时间服务不能因提供方替换而分裂。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aurora_bot.bot.store import JournalBotState
from aurora_bot.clock import PersistentBotClock
from aurora_bot.contracts.bot import WakeStatus
from aurora_bot.contracts.operation import OperationKind, OperationRequest, OperationStatus
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.kernel import BuiltinSource, compose_managed, module
from aurora_bot.runtime import create_runtime
from tests.ai.endpoint_support import _config
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.contracts.pkgs.bot import BotStateStore
    from aurora_bot.contracts.pkgs.clock import BotClock
    from aurora_bot.contracts.pkgs.operations import OperationRegistry
    from aurora_bot.kernel import ModuleContext

_DUE = datetime(2026, 10, 18, tzinfo=UTC)
_GOAL = "aurora:goal/selected-state"
_WAKE = "aurora:wake/selected-state"


async def _schedule(registry: OperationRegistry, state: BotStateStore) -> None:
    """只使用正式命令保存目标和安排，版本来自当前选中主体。"""
    arguments = (
        ("goal_set", {"goal_id": _GOAL, "purpose": "核对选中主体", "success_condition": "核对完成"}),
        ("wake_schedule", {"wake_id": _WAKE, "goal_id": _GOAL, "due_at": _DUE.isoformat(), "message": "继续核对主体"}),
    )
    for action, data in arguments:
        version = (await state.snapshot()).version
        request = OperationRequest(
            f"selected-{action}",
            state.bot_id,
            "test",
            ResourceRef(ResourceKey("aurora", "bot", "command", action), "2"),
            OperationKind.COMMAND,
            {**data, "expected_version": version},
        )
        result = await registry.dispatch(request)
        assert result.status is OperationStatus.SUCCEEDED
        assert (await state.snapshot()).version > version


def test_selected_subject_is_used_by_public_commands_and_default_clock(configured_project: Path) -> None:
    """默认配置中的主体身份不能泄漏到替换后的命令或等待安排中。"""
    config = _config(configured_project, "aurora:ai/endpoint/default")

    @module(name="selected_subject", provides="bot", requires="world", priority=10)
    def selected(context: ModuleContext) -> BotStateStore:
        """提供真实世界投影，以不同身份识别私有默认状态误用。"""
        return JournalBotState(context.get("world"), "lab:bot/selected")

    async def scenario() -> None:
        """真实状态、命令、默认时间服务和引擎共享一个主体。"""
        model = FakeModel()
        handle = await compose_managed(config, (*BuiltinSource().discover(), selected), instances=(("ai", model),))
        create_runtime(handle.assembly, output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await handle.activate(stop)
            state = handle.assembly.get("bot")
            await _schedule(handle.assembly.get("operations"), state)
            assert state.bot_id == "lab:bot/selected"
            await handle.assembly.get("clock").evaluate_once(_DUE)
            assert (await state.snapshot()).wake(_WAKE).status is WakeStatus.COMPLETED
            assert model.requests
            assert "核对选中主体" in model.requests[0].messages[0].content
        finally:
            await handle.close()

    asyncio.run(scenario())


def test_selected_clock_can_depend_on_default_subject_without_losing_launcher(configured_project: Path) -> None:
    """替换时间服务依赖默认主体时不能形成组合环，也不能接线到失选实例。"""
    config = _config(configured_project, "aurora:ai/endpoint/default")
    clocks: list[PersistentBotClock] = []

    @module(name="selected_clock", provides="clock", requires=("bot", "world.reader"), priority=10)
    def selected(context: ModuleContext) -> BotClock:
        """真实时间服务通过契约获得默认主体。"""
        clock = PersistentBotClock(context.get("bot"), context.get("world.reader"), now=lambda: _DUE)
        clocks.append(clock)
        return clock

    async def scenario() -> None:
        """实际运行一次到期认知，以世界终态证明接线落在正确实例。"""
        model = FakeModel()
        handle = await compose_managed(config, (*BuiltinSource().discover(), selected), instances=(("ai", model),))
        create_runtime(handle.assembly, output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await handle.activate(stop)
            state = handle.assembly.get("bot")
            await _schedule(handle.assembly.get("operations"), state)
            assert handle.assembly.get("clock") is clocks[0]
            await clocks[0].evaluate_once()
            assert (await state.snapshot()).wake(_WAKE).status is WakeStatus.COMPLETED
            assert model.requests
        finally:
            await handle.close()

    asyncio.run(scenario())
