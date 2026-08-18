from __future__ import annotations

import pytest

from src.contracts import AgentTree, ChatMessage, ToolCall
from src.prompt import PromptAssembler, PromptCatalog


def _assembler(*, limit: int = 1_000) -> PromptAssembler:
    return PromptAssembler(
        PromptCatalog(("You are Aurora.", "The world continues between messages."), {"root": "Act as the root."}),
        max_characters=limit,
    )


def test_assembler_emits_one_system_then_node_transcript() -> None:
    tree = AgentTree.create("tree", "root", "root", "quality-model", "hello")
    tree = tree.append(
        "root",
        ChatMessage.assistant(tool_calls=(ToolCall("call-1", "clock", {}),)),
    )
    tree = tree.append("root", ChatMessage.tool("call-1", "12:00"))

    messages = _assembler().assemble(tree, "root")

    assert [message.role for message in messages] == ["system", "message", "assistant", "tool"]
    assert messages[0].content == ("You are Aurora.\n\nThe world continues between messages.\n\nAct as the root.")


def test_assembler_fails_visibly_when_context_is_too_large() -> None:
    tree = AgentTree.create("tree", "root", "root", "quality-model", "hello")

    with pytest.raises(ValueError, match="prompt exceeds character limit"):
        _assembler(limit=10).assemble(tree, "root")


def test_assembler_rejects_missing_profile() -> None:
    tree = AgentTree.create("tree", "root", "missing", "quality-model", "hello")

    with pytest.raises(ValueError, match="missing prompt"):
        _assembler().assemble(tree, "root")


def test_prompt_catalog_and_assembler_require_non_empty_bounds() -> None:
    with pytest.raises(ValueError, match="system fragment"):
        PromptCatalog((), {"root": "prompt"})
    with pytest.raises(ValueError, match="profile prompt"):
        PromptCatalog(("system",), {})
    with pytest.raises(ValueError, match="must be positive"):
        PromptAssembler(PromptCatalog(("system",), {"root": "prompt"}), max_characters=0)
