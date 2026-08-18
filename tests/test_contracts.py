from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.contracts import (
    AgentDefinition,
    AgentNode,
    AgentStatus,
    AgentTree,
    ChatMessage,
    ModelRequest,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    TreeStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _empty_assistant() -> ChatMessage:
    return ChatMessage.assistant()


def _agent(
    definition_id: str = "root",
    profile: str = "root",
    model: str = "model",
    tools: frozenset[str] = frozenset(),
    children: frozenset[str] = frozenset(),
) -> AgentDefinition:
    return AgentDefinition(definition_id, "Test Agent.", profile, model, tools, children)


def test_chat_message_accepts_exactly_four_roles() -> None:
    assert ChatMessage.system("system").role == "system"
    assert ChatMessage.message("message").role == "message"
    assert ChatMessage.assistant("assistant").role == "assistant"
    assert ChatMessage.tool("call", "tool").role == "tool"


def test_tool_message_must_match_an_unanswered_call() -> None:
    tree = AgentTree.create("tree", "root", _agent(), "hello")

    with pytest.raises(ValueError, match="must match"):
        tree.append("root", ChatMessage.tool("missing", "result"))


def test_node_rejects_duplicate_call_ids_across_assistant_messages() -> None:
    call = ToolCall("same", "echo", {})

    with pytest.raises(ValueError, match="unique"):
        AgentNode(
            "root",
            None,
            None,
            "root",
            "root",
            "model",
            frozenset({"echo"}),
            (
                ChatMessage.message("hello"),
                ChatMessage.assistant(tool_calls=(call,)),
                ChatMessage.tool("same", "one"),
                ChatMessage.assistant(tool_calls=(call,)),
            ),
        )


def test_tree_rejects_missing_parent() -> None:
    root = AgentNode("root", None, None, "root", "root", "model", frozenset(), (ChatMessage.message("hello"),))
    orphan = AgentNode(
        "orphan",
        "missing",
        "call",
        "worker",
        "worker",
        "model",
        frozenset(),
        (ChatMessage.message("work"),),
    )

    with pytest.raises(ValueError, match="missing parent"):
        AgentTree("tree", "root", (root, orphan))


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: ToolCall("", "tool", {}), "requires call_id"),
        (lambda: ChatMessage.system(""), "invalid system"),
        (_empty_assistant, "invalid assistant"),
        (lambda: ChatMessage.tool("", "result"), "invalid tool"),
        (lambda: ToolDefinition("", "description", {}), "requires name"),
        (lambda: ToolOutput(""), "must not be empty"),
    ],
)
def test_model_value_objects_reject_empty_required_fields(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_assistant_rejects_duplicate_call_ids_in_one_message() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        ChatMessage.assistant(
            tool_calls=(ToolCall("same", "one", {}), ToolCall("same", "two", {})),
        )


def test_model_request_requires_model_one_system_and_unique_tools() -> None:
    messages = (ChatMessage.system("system"), ChatMessage.message("hello"))
    tool = ToolDefinition("echo", "Echo.", {})

    with pytest.raises(ValueError, match="requires model"):
        ModelRequest("", messages)
    with pytest.raises(ValueError, match="start with system"):
        ModelRequest("model", (ChatMessage.message("hello"),))
    with pytest.raises(ValueError, match="only one"):
        ModelRequest("model", (ChatMessage.system("one"), ChatMessage.system("two")))
    with pytest.raises(ValueError, match="must be unique"):
        ModelRequest("model", messages, (tool, tool))


def test_agent_node_requires_parent_pairing_message_and_terminal_outcome() -> None:
    message = (ChatMessage.message("hello"),)

    with pytest.raises(ValueError, match="node_id"):
        AgentNode("", None, None, "root", "root", "model", frozenset(), message)
    with pytest.raises(ValueError, match="root node"):
        AgentNode("root", None, "call", "root", "root", "model", frozenset(), message)
    with pytest.raises(ValueError, match="child node"):
        AgentNode("child", "root", None, "worker", "worker", "model", frozenset(), message)
    with pytest.raises(ValueError, match="must start"):
        AgentNode("root", None, None, "root", "root", "model", frozenset(), ())
    with pytest.raises(ValueError, match="only by PromptAssembler"):
        AgentNode(
            "root",
            None,
            None,
            "root",
            "root",
            "model",
            frozenset(),
            (ChatMessage.message("hello"), ChatMessage.system("system")),
        )
    with pytest.raises(ValueError, match="requires result"):
        AgentNode("root", None, None, "root", "root", "model", frozenset(), message, AgentStatus.COMPLETED)
    with pytest.raises(ValueError, match="requires error"):
        AgentNode("root", None, None, "root", "root", "model", frozenset(), message, AgentStatus.FAILED)


def test_tree_requires_identity_unique_nodes_and_matching_root_status() -> None:
    root = AgentNode("root", None, None, "root", "root", "model", frozenset(), (ChatMessage.message("hello"),))
    completed = AgentNode(
        "root",
        None,
        None,
        "root",
        "root",
        "model",
        frozenset(),
        (ChatMessage.message("hello"), ChatMessage.assistant("done")),
        AgentStatus.COMPLETED,
        "done",
    )

    with pytest.raises(ValueError, match="requires tree_id"):
        AgentTree("", "root", (root,))
    with pytest.raises(ValueError, match="must be unique"):
        AgentTree("tree", "root", (root, root))
    with pytest.raises(ValueError, match="exactly one root"):
        AgentTree("tree", "missing", (root,))
    with pytest.raises(ValueError, match=r"running.*terminal"):
        AgentTree("tree", "root", (completed,))
    with pytest.raises(ValueError, match=r"completed.*requires"):
        AgentTree("tree", "root", (root,), TreeStatus.COMPLETED)


def test_only_tool_messages_may_answer_pending_calls() -> None:
    call = ToolCall("call", "echo", {})
    with pytest.raises(ValueError, match="only tool messages"):
        AgentNode(
            "root",
            None,
            None,
            "root",
            "root",
            "model",
            frozenset({"echo"}),
            (
                ChatMessage.message("hello"),
                ChatMessage.assistant(tool_calls=(call,)),
                ChatMessage.message("interrupt"),
            ),
        )
