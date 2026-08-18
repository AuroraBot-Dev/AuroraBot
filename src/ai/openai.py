"""把 AuroraBot 四角色消息映射到 OpenAI-compatible 请求形状。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.contracts import ChatMessage, ToolDefinition


def to_openai_messages(messages: tuple[ChatMessage, ...]) -> list[dict[str, Any]]:
    """仅在 Provider 边界把领域 role ``message`` 映射为 ``user``。"""
    result: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {
            "role": "user" if message.role == "message" else message.role,
            "content": message.content,
        }
        if message.role == "assistant" and message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(dict(call.arguments), ensure_ascii=False)},
                }
                for call in message.tool_calls
            ]
        if message.role == "tool":
            item["tool_call_id"] = message.tool_call_id
        result.append(item)
    return result


def to_openai_tools(tools: tuple[ToolDefinition, ...]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            },
        }
        for tool in tools
    ]
