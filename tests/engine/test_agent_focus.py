from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aurora_bot.cadence.state import launch_data, read_launch
from aurora_bot.contracts import ChatMessage, CognitionRequest
from aurora_bot.world import SqlAlchemyWorldJournal
from tests.support.engine import make_engine
from tests.support.model import ScriptedModel
from tests.support.prompt import _agent

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.contracts.memory import MemoryRequest


def test_goal_focus_survives_persistence_and_reaches_recall(tmp_path: Path) -> None:
    focus = ("aurora:goal/check",)
    request = CognitionRequest(
        "核对结果",
        agent=_agent().definition_id,
        run_id="focus",
        focus_goal_ids=focus,
        memory_scopes=frozenset({"test:world/allowed"}),
    )
    assert read_launch(launch_data(request)) == request
    seen = []

    class Memory:
        async def recall(self, memory_request: MemoryRequest) -> None:
            seen.append(memory_request)

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        try:
            engine = make_engine(
                ScriptedModel([ChatMessage.assistant("完成")]), (_agent(),), world=world, memory=Memory()
            )
            await engine.execute(request)
            assert seen[0].focus_goal_ids == focus
            assert seen[0].scopes == request.memory_scopes
            started = await world.commit("focus:run:started")
            assert started is not None and started.data["focus_goal_ids"] == focus
        finally:
            await world.close()

    asyncio.run(scenario())
