from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from aurora_bot.contracts import ChatMessage, ModelRequest, ToolCall, ToolDefinition, ToolOutput, ToolStatus
from tests.support.model import fake_endpoint

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_bot.contracts.model_binding import ModelBinding


def test_chat_message_accepts_exactly_four_roles() -> None:
    assert ChatMessage.system("system").role == "system"
    assert ChatMessage.message("message").role == "message"
    assert ChatMessage.assistant("assistant").role == "assistant"
    assert ChatMessage.tool("call", "tool").role == "tool"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: ToolCall("", "tool", {}), "requires call_id"),
        (lambda: ChatMessage.system(""), "invalid system"),
        (ChatMessage.assistant, "invalid assistant"),
        (lambda: ChatMessage.tool("", "result"), "invalid tool"),
        (lambda: ToolDefinition("", "description", {}), "需要非空"),
        (lambda: ToolOutput(""), "must not be empty"),
    ],
)
def test_model_value_objects_reject_empty_required_fields(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_tool_output_has_three_statuses_and_derives_is_error() -> None:
    assert ToolOutput("done").status is ToolStatus.SUCCEEDED
    assert not ToolOutput("done").is_error
    assert ToolOutput("failed", status=ToolStatus.FAILED).is_error
    assert ToolOutput("unknown", status=ToolStatus.UNKNOWN).is_error
    with pytest.raises(TypeError, match="ToolStatus"):
        ToolOutput("invalid", status=cast("ToolStatus", "failed"))


def test_tool_definition_deep_freezes_nested_json_schema() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["one", "two"]}},
        "required": ["mode"],
    }
    definition = ToolDefinition("test:tool/definition/choose", "Choose a mode.", schema)
    schema["properties"]["mode"]["enum"].append("mutated")
    schema["required"].append("mutated")
    mode = definition.parameters["properties"]["mode"]
    assert mode["enum"] == ("one", "two")
    assert definition.parameters["required"] == ("mode",)
    with pytest.raises(TypeError):
        mode["type"] = "integer"
    with pytest.raises(TypeError):
        cast("dict[str, Any]", definition.parameters)["new"] = True


def test_assistant_rejects_duplicate_call_ids_in_one_message() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        ChatMessage.assistant(tool_calls=(ToolCall("same", "one", {}), ToolCall("same", "two", {})))


def test_model_request_requires_model_one_system_and_unique_tools() -> None:
    messages = (ChatMessage.system("system"), ChatMessage.message("hello"))
    tool = ToolDefinition("test:tool/definition/echo", "Echo.", {})
    with pytest.raises(TypeError, match="完整端点快照"):
        ModelRequest(cast("ModelBinding", None), messages)
    with pytest.raises(ValueError, match="start with system"):
        ModelRequest(fake_endpoint("test:ai/endpoint/model"), (ChatMessage.message("hello"),))
    with pytest.raises(ValueError, match="only one"):
        ModelRequest(fake_endpoint("test:ai/endpoint/model"), (ChatMessage.system("one"), ChatMessage.system("two")))
    with pytest.raises(ValueError, match="must be unique"):
        ModelRequest(fake_endpoint("test:ai/endpoint/model"), messages, (tool, tool))
