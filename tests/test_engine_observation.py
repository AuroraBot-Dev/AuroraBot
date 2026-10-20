"""世界写入、观察范围与记忆召回之间的行为边界。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurorabot.agents import AgentCatalog
from aurorabot.contracts import AgentTree, ChatMessage, MemorySnapshot, ToolCall, ToolScopes, WorldFrontier
from aurorabot.contracts.memory import MemoryRequest
from aurorabot.engine import AgentTreeRunner
from aurorabot.tools import DELEGATE_TOOL, DelegateTool, ToolRegistry
from aurorabot.world import SqlAlchemyWorldJournal
from tests.model_support import ScriptedModel as FakeModel
from tests.test_engine_runtime import ScopedEchoTool, _agent, _assembler

if TYPE_CHECKING:
    from pathlib import Path


class RecordingMemory:
    def __init__(self) -> None:
        self.scopes: list[frozenset[str] | None] = []

    async def recall(self, request: MemoryRequest | None = None) -> MemorySnapshot:
        request = request or MemoryRequest()
        self.scopes.append(request.scopes)
        return MemorySnapshot(request.observed_at or datetime(2026, 1, 1, tzinfo=UTC), ())


class PublishOnlyTool(ScopedEchoTool):
    def resolve_scopes(self, call: ToolCall) -> ToolScopes:
        return ToolScopes(publish=frozenset({self.scope}))


@pytest.mark.parametrize("memory_scopes", [None, frozenset(), frozenset({"test:world/conversation"})])
def test_internal_and_tool_effects_do_not_change_recall_or_observation_scope(
    tmp_path: Path, memory_scopes: frozenset[str] | None
) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        tool = PublishOnlyTool("test:world/published")
        definition = _agent(tools=frozenset({tool.definition.name}))
        model = FakeModel(
            [
                ChatMessage.assistant(tool_calls=(ToolCall("echo", tool.definition.name, {"value": "你好"}),)),
                ChatMessage.assistant("完成"),
            ]
        )
        memory = RecordingMemory()
        tree = AgentTree.create(
            "tree",
            "root",
            definition,
            "开始",
            WorldFrontier({"test:world/conversation": 0}),
            memory_scopes=memory_scopes,
        )
        try:
            result = await AgentTreeRunner(
                model,
                _assembler(),
                AgentCatalog((definition,)),
                ToolRegistry((tool,)),
                world=journal,
                memory=memory,
            ).run(tree)
            assert memory.scopes == [memory_scopes, memory_scopes]
            node = result.node("root")
            assert node.observation_scopes == {"test:world/conversation"}
            assert node.observed_frontier.sequence("aurora:run/tree") > 0
            assert node.observed_frontier.sequence("test:world/published") > 0
        finally:
            await journal.close()

    asyncio.run(scenario())


def test_delegation_preserves_trigger_and_explicit_memory_scope() -> None:
    root = _agent(tools=frozenset({DELEGATE_TOOL}), children=frozenset({"worker"}))
    worker = _agent("worker", "worker")
    agents = AgentCatalog((root, worker))
    call = ToolCall("delegate", DELEGATE_TOOL, {"agent": worker.definition_id, "instruction": "检查"})
    model = FakeModel(
        [ChatMessage.assistant(tool_calls=(call,)), ChatMessage.assistant("检查完成"), ChatMessage.assistant("完成")]
    )
    memory = RecordingMemory()
    scopes = frozenset({"test:world/conversation"})
    tree = AgentTree.create("tree", "root", root, "开始", caused_by="event", memory_scopes=scopes)
    result = asyncio.run(
        AgentTreeRunner(model, _assembler(), agents, ToolRegistry((DelegateTool(agents),)), memory=memory).run(tree)
    )

    assert result.caused_by == "event"
    assert all(node.memory_scopes == scopes for node in result.nodes)
    assert memory.scopes == [scopes, scopes, scopes]
