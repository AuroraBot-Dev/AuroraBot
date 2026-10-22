from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from aurora_bot.contracts import ChatMessage, CognitionRequest, ModelRequest
from aurora_bot.world import SqlAlchemyWorldJournal
from aurora_kernel import Context, namespace
from tests.support.engine import make_engine
from tests.support.model import ScriptedModel
from tests.support.prompt import _agent

if TYPE_CHECKING:
    from pathlib import Path


def test_run_keeps_its_selected_definition_when_the_catalog_changes(tmp_path: Path) -> None:
    original = _agent()
    selected = [original]

    @namespace("catalog_override")
    def override(ctx: Context) -> None:
        pass

    @override.hook("aurora:kernel/module/agents:get", priority=10)
    def get(ctx: Context, identity: str):
        return selected[0]

    @override.hook("aurora:kernel/module/ai:complete", priority=10)
    async def complete(ctx: Context, request: ModelRequest) -> ChatMessage:
        selected[0] = replace(original, description="已修改的配置")
        assert request.resources[0] == original.ref
        return ChatMessage.assistant("完成")

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        try:
            engine = make_engine(ScriptedModel([]), (original,), world=world, extensions=(override,))
            await engine.execute(CognitionRequest("检查", agent=original.definition_id, run_id="snapshot"))
            started = await world.commit("snapshot:run:started")
            requested = await world.commit("snapshot:model:0:requested")
            assert started is not None and requested is not None
            assert started.data["definition_ref"] == requested.data["definition_ref"]
            assert requested.data["definition_ref"]["revision"] == original.ref.revision
            assert selected[0].ref != original.ref
        finally:
            await world.close()

    asyncio.run(scenario())
