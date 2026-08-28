"""把 AuroraBot 四角色消息映射到 OpenAI-compatible 请求形状。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from src.utils import thaw_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from src.contracts import ChatMessage, ToolDefinition

_PROVIDER_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")
_PROVIDER_TOOL_NAME_MAX_LENGTH = 64
_ALIAS_SEPARATOR = "__"
_INVALID_NAME_REPLACEMENT = "__"


def openai_tool_name_map(names: Iterable[str]) -> dict[str, str]:
    """为领域 Tool ID 生成 OpenAI-compatible 的稳定请求级别名。"""
    aliases: dict[str, str] = {}
    used: set[str] = set()
    for name in sorted(set(names)):
        alias = _openai_tool_name(name)
        if alias in used:
            raise ValueError(f"Provider Tool 名称发生冲突：{alias}")
        aliases[name] = alias
        used.add(alias)
    return aliases


def to_openai_messages(
    messages: tuple[ChatMessage, ...],
    tool_names: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """仅在 Provider 边界把领域 role ``message`` 映射为 ``user``。"""
    aliases = tool_names or openai_tool_name_map(call.name for message in messages for call in message.tool_calls)
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
                    "function": {
                        "name": aliases[call.name],
                        "arguments": json.dumps(dict(call.arguments), ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        if message.role == "tool":
            item["tool_call_id"] = message.tool_call_id
        result.append(item)
    return result


def to_openai_tools(
    tools: tuple[ToolDefinition, ...],
    tool_names: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    aliases = tool_names or openai_tool_name_map(tool.name for tool in tools)
    return [
        {
            "type": "function",
            "function": {
                "name": aliases[tool.name],
                "description": tool.description,
                "parameters": thaw_json(tool.parameters),
            },
        }
        for tool in tools
    ]


def _openai_tool_name(name: str) -> str:
    if len(name) <= _PROVIDER_TOOL_NAME_MAX_LENGTH and _PROVIDER_TOOL_NAME.fullmatch(name):
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-zA-Z0-9_-]", _INVALID_NAME_REPLACEMENT, name).strip("_") or "tool"
    prefix_length = _PROVIDER_TOOL_NAME_MAX_LENGTH - len(digest) - len(_ALIAS_SEPARATOR)
    return f"{slug[:prefix_length]}{_ALIAS_SEPARATOR}{digest}"
