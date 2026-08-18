from __future__ import annotations

import json

from src.ai import to_openai_messages, to_openai_tools
from src.contracts import ChatMessage, ToolCall, ToolDefinition


def test_openai_adapter_maps_only_message_role_to_user() -> None:
    messages = (
        ChatMessage.system("system"),
        ChatMessage.message("event"),
        ChatMessage.assistant(tool_calls=(ToolCall("call-1", "clock", {"zone": "UTC"}),)),
        ChatMessage.tool("call-1", "12:00"),
    )

    result = to_openai_messages(messages)

    assert [item["role"] for item in result] == ["system", "user", "assistant", "tool"]
    assert result[2]["tool_calls"][0]["function"]["name"] == "clock"
    assert json.loads(result[2]["tool_calls"][0]["function"]["arguments"]) == {"zone": "UTC"}
    assert result[3]["tool_call_id"] == "call-1"


def test_openai_tool_adapter_preserves_native_schema() -> None:
    schema = {"type": "object", "properties": {"value": {"type": "string"}}}
    result = to_openai_tools((ToolDefinition("echo", "Echo text.", schema),))

    assert result == [
        {
            "type": "function",
            "function": {"name": "echo", "description": "Echo text.", "parameters": schema},
        }
    ]
