"""主体状态、公开命令与时间服务不能因提供方替换而分裂。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from test_assembly import FakeModel
from test_model_provenance import _config

from aurorabot.bot.store import JournalBotState
from aurorabot.clock import PersistentBotClock
from aurorabot.contracts.bot import WakeStatus
from aurorabot.contracts.operation import OperationKind, OperationRequest, OperationStatus
from aurorabot.contracts.pkgs.ai import Model
from aurorabot.contracts.pkgs.bot import BotStateStore
from aurorabot.contracts.pkgs.clock import BotClock
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.contracts.pkgs.world import WorldJournal, WorldReader
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.kernel import BuiltinSource, compose_managed, module
from aurorabot.runtime import create_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.kernel import ModuleContext

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

    @module(name="selected_subject", provides=BotStateStore, requires=WorldJournal, priority=10)
    def selected(context: ModuleContext) -> BotStateStore:
        """提供真实世界投影，以不同身份识别私有默认状态误用。"""
        return JournalBotState(context.get(WorldJournal), "lab:bot/selected")

    async def scenario() -> None:
        """真实状态、命令、默认时间服务和引擎共享一个主体。"""
        model = FakeModel()
        handle = await compose_managed(config, (*BuiltinSource().discover(), selected), instances=((Model, model),))
        create_runtime(handle.assembly, output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await handle.activate(stop)
            state = handle.assembly.get(BotStateStore)
            await _schedule(handle.assembly.get(OperationRegistry), state)
            assert state.bot_id == "lab:bot/selected"
            await handle.assembly.get(BotClock).evaluate_once(_DUE)
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

    @module(name="selected_clock", provides=BotClock, requires=(BotStateStore, WorldReader), priority=10)
    def selected(context: ModuleContext) -> BotClock:
        """真实时间服务通过契约获得默认主体。"""
        clock = PersistentBotClock(context.get(BotStateStore), context.get(WorldReader), now=lambda: _DUE)
        clocks.append(clock)
        return clock

    async def scenario() -> None:
        """实际运行一次到期认知，以世界终态证明接线落在正确实例。"""
        model = FakeModel()
        handle = await compose_managed(config, (*BuiltinSource().discover(), selected), instances=((Model, model),))
        create_runtime(handle.assembly, output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await handle.activate(stop)
            state = handle.assembly.get(BotStateStore)
            await _schedule(handle.assembly.get(OperationRegistry), state)
            assert handle.assembly.get(BotClock) is clocks[0]
            await clocks[0].evaluate_once()
            assert (await state.snapshot()).wake(_WAKE).status is WakeStatus.COMPLETED
            assert model.requests
        finally:
            await handle.close()

    asyncio.run(scenario())
