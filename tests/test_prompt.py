from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.contracts import (
    AgentDefinition,
    AgentTree,
    ChatMessage,
    MemoryScopeSnapshot,
    MemorySnapshot,
    ToolCall,
    WorldCommit,
    WorldFrontier,
)
from src.prompt import PromptAssembler, PromptCatalog


def _assembler(*, limit: int = 1_000) -> PromptAssembler:
    return PromptAssembler(
        PromptCatalog(("You are Aurora.", "The world continues between messages."), {"root": "Act as the root."}),
        max_characters=limit,
    )


def _agent(prompt: str = "root") -> AgentDefinition:
    return AgentDefinition("agent", "Test Agent.", prompt, "quality-model", frozenset(), frozenset())


def test_assembler_emits_one_system_then_node_transcript() -> None:
    tree = AgentTree.create("tree", "root", _agent(), "hello")
    tree = tree.append(
        "root",
        ChatMessage.assistant(tool_calls=(ToolCall("call-1", "clock", {}),)),
    )
    tree = tree.append("root", ChatMessage.tool("call-1", "12:00"))

    messages = _assembler().assemble(tree, "root")

    assert [message.role for message in messages] == ["system", "message", "assistant", "tool"]
    assert messages[0].content == ("You are Aurora.\n\nThe world continues between messages.\n\nAct as the root.")


def test_assembler_fails_visibly_when_context_is_too_large() -> None:
    tree = AgentTree.create("tree", "root", _agent(), "hello")

    with pytest.raises(ValueError, match="prompt exceeds character limit"):
        _assembler(limit=10).assemble(tree, "root")


def test_assembler_rejects_missing_agent_prompt() -> None:
    tree = AgentTree.create("tree", "root", _agent("missing"), "hello")

    with pytest.raises(ValueError, match="missing Agent prompt"):
        _assembler().assemble(tree, "root")


def test_assembler_injects_memory_snapshot_into_system() -> None:
    commit = WorldCommit(
        "c-1",
        "environment.message",
        "qq",
        "有人发来消息",
        datetime.now(UTC),
        {"qq:group": 1},
        WorldFrontier(),
        {"message_id": 1},
    )
    memory = MemorySnapshot(commit.occurred_at, (MemoryScopeSnapshot("qq:group", 1, (commit,)),))
    tree = AgentTree.create("tree", "root", _agent(), "hello")

    messages = _assembler().assemble(tree, "root", memory=memory)

    assert "最近一小时的世界活动" in messages[0].content
    assert "scope：qq:group" in messages[0].content
    assert "有人发来消息" in messages[0].content
    assert '"message_id":1' in messages[0].content


def test_prompt_catalog_and_assembler_require_non_empty_bounds() -> None:
    with pytest.raises(ValueError, match="system fragment"):
        PromptCatalog((), {"root": "prompt"})
    with pytest.raises(ValueError, match="Agent prompt"):
        PromptCatalog(("system",), {})
    with pytest.raises(ValueError, match="must be positive"):
        PromptAssembler(PromptCatalog(("system",), {"root": "prompt"}), max_characters=0)
