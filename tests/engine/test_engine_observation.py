from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts import ChatMessage, CognitionRequest, MemorySnapshot, ToolCall, ToolScopes, WorldFrontier
from aurora_bot.world import SqlAlchemyWorldJournal
from tests.engine.support import RecordingTool
from tests.support.engine import make_engine
from tests.support.model import ScriptedModel
from tests.support.prompt import _agent

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.contracts.memory import MemoryRequest


class RecordingMemory:
    def __init__(self) -> None:
        self.scopes: list[frozenset[str] | None] = []

    async def recall(self, request: MemoryRequest) -> MemorySnapshot:
        self.scopes.append(request.scopes)
        return MemorySnapshot(datetime(2026, 1, 1, tzinfo=UTC), ())


class PublishOnlyTool(RecordingTool):
    def resolve_scopes(self, call: ToolCall) -> ToolScopes:
        return ToolScopes(publish=frozenset({"test:world/published"}))


@pytest.mark.parametrize("memory_scopes", [None, frozenset(), frozenset({"test:world/conversation"})])
def test_internal_and_tool_effects_do_not_change_recall_or_observation_scope(
    tmp_path: Path, memory_scopes: frozenset[str] | None
) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        tool = PublishOnlyTool()
        definition = replace(_agent(), tools=frozenset({tool.definition.name}))
        model = ScriptedModel(
            [
                ChatMessage.assistant(tool_calls=(ToolCall("echo", tool.definition.name, {"value": "你好"}),)),
                ChatMessage.assistant("完成"),
            ]
        )
        memory = RecordingMemory()
        engine = make_engine(model, (definition,), world=journal, memory=memory, tools=(tool,))
        try:
            result = await engine.execute(
                CognitionRequest(
                    "开始",
                    run_id="run",
                    agent=definition.definition_id,
                    frontier=WorldFrontier({"test:world/conversation": 0}),
                    memory_scopes=memory_scopes,
                )
            )
            assert result.status == "completed"
            assert memory.scopes == [memory_scopes, memory_scopes]
            requested = await journal.commit("run:model:1:requested")
            assert requested is not None and requested.based_on.sequence("test:world/published") > 0
            assert await journal.commit("run:model:1:world-delta") is None
        finally:
            await journal.close()

    asyncio.run(scenario())
