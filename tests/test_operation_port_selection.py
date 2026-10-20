"""终端与生成的模型工具共用内核实际选中的操作路由。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING

from test_assembly import FakeModel

from aurora import load_config
from aurorabot.contracts import ToolCall, ToolOutput
from aurorabot.contracts.operation import OPERATION_CONTRIBUTIONS
from aurorabot.contracts.pkgs.ai import Model
from aurorabot.contracts.pkgs.artifacts import ArtifactStore
from aurorabot.contracts.pkgs.bot import BotStateStore
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.contracts.pkgs.resources import ResourceCatalog
from aurorabot.contracts.pkgs.tools import ToolRegistry
from aurorabot.contracts.pkgs.world import WorldJournal
from aurorabot.kernel import BuiltinSource, compose, module
from aurorabot.operations.registry import OperationRegistry as Registry
from aurorabot.runtime import create_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.contracts.operation import OperationRequest, OperationResult
    from aurorabot.kernel import ModuleContext


class _SelectedRegistry(Registry):
    async def dispatch(self, request: OperationRequest) -> OperationResult:
        result = await super().dispatch(request)
        return replace(result, data={**result.data, "selected_registry": True})


def test_tool_and_terminal_dispatch_to_the_same_selected_registry(configured_project: Path) -> None:
    @module(
        name="zzz_selected_registry",
        provides=OperationRegistry,
        requires=(BotStateStore, ResourceCatalog, WorldJournal, ArtifactStore),
        consumes=OPERATION_CONTRIBUTIONS,
        priority=10,
    )
    def selected(context: ModuleContext) -> OperationRegistry:
        return _SelectedRegistry(
            context.get(BotStateStore).bot_id,
            context.contributions(OPERATION_CONTRIBUTIONS),
            context.get(ResourceCatalog),
            context.get(WorldJournal),
            artifacts=context.get(ArtifactStore),
        )

    async def scenario() -> None:
        assembly = compose(
            load_config(configured_project), (*BuiltinSource().discover(), selected), ((Model, FakeModel()),)
        )
        runtime = create_runtime(assembly, output=lambda _: None)
        try:
            result = await assembly.get(ToolRegistry).execute(
                ToolCall("selected-state", "aurora:tool/definition/bot_state", {})
            )
            assert isinstance(result, ToolOutput) and not result.is_error
            assert json.loads(result.content)["selected_registry"] is True
            response = await runtime.terminal.dispatch_terminal("/call aurora:bot/query/state {}")
            assert not response.is_error
            assert json.loads(response.text or "{}")["data"]["selected_registry"] is True
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
