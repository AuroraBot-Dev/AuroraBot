"""模型响应解析工具 —— Chat Completions 与 Responses 输出规范化。

从 vnext.py 按职责分离出来的纯函数，负责工具序列化、
响应解析、费用提取和输出验证。不依赖网关服务状态。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from jsonschema import ValidationError, validate

from src.ai.models import compute_cost
from src.contracts.model import (
    ModelCapabilityError,
    ModelGatewayError,
    ModelRequest,
    ModelUsage,
    ToolCall,
    ToolDefinition,
)


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    ALIAS_COLLISION = "tool alias collision"
    NO_ASSISTANT_MESSAGE = "Chat provider returned no assistant message"


# ═══════════════════════════════════════════════════════════
# 工具序列化
# ═══════════════════════════════════════════════════════════


def provider_tools(
    tools: tuple[ToolDefinition, ...], *, responses: bool
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    definitions: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    for tool in tools:
        alias = f"aurora_{hashlib.sha256(tool.name.encode()).hexdigest()[:20]}"
        if alias in aliases:
            raise ModelCapabilityError(_Msg.ALIAS_COLLISION)
        aliases[alias] = tool.name
        if responses:
            definitions.append(
                {
                    "type": "function",
                    "name": alias,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                }
            )
        else:
            definitions.append(
                {
                    "type": "function",
                    "function": {"name": alias, "description": tool.description, "parameters": tool.parameters_schema},
                }
            )
    return definitions, aliases


# ═══════════════════════════════════════════════════════════
# Chat Completions 响应解析
# ═══════════════════════════════════════════════════════════


def chat_message(response: object) -> Any:
    try:
        return response.choices[0].message  # type: ignore[attr-defined]
    except (AttributeError, IndexError, TypeError) as error:
        raise ModelGatewayError(_Msg.NO_ASSISTANT_MESSAGE) from error


def chat_assistant_item(message: object) -> dict[str, Any]:
    item: dict[str, Any] = {"role": "assistant", "content": getattr(message, "content", None)}
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning is not None:
        item["reasoning_content"] = reasoning
    calls = getattr(message, "tool_calls", None)
    if calls:
        item["tool_calls"] = [json_item(call) for call in calls]
    return item


def chat_tool_calls(message: object, aliases: dict[str, str]) -> tuple[tuple[ToolCall, ...], tuple[str, ...]]:
    calls: list[ToolCall] = []
    diagnostics: list[str] = []
    for raw in getattr(message, "tool_calls", None) or []:
        function = getattr(raw, "function", None)
        alias = str(getattr(function, "name", ""))
        name = aliases.get(alias)
        if name is None:
            diagnostics.append(f"provider returned unknown tool alias: {alias}")
            continue
        arguments = parse_arguments(getattr(function, "arguments", "{}"), diagnostics)
        calls.append(ToolCall(str(getattr(raw, "id", "")), name, arguments))
    return tuple(calls), tuple(diagnostics)


# ═══════════════════════════════════════════════════════════
# Responses 响应解析
# ═══════════════════════════════════════════════════════════


def response_tool_calls(
    items: tuple[dict[str, Any], ...], aliases: dict[str, str]
) -> tuple[tuple[ToolCall, ...], tuple[str, ...]]:
    calls: list[ToolCall] = []
    diagnostics: list[str] = []
    for item in items:
        if item.get("type") != "function_call":
            continue
        alias = str(item.get("name", ""))
        name = aliases.get(alias)
        if name is None:
            diagnostics.append(f"provider returned unknown tool alias: {alias}")
            continue
        calls.append(
            ToolCall(str(item.get("call_id", "")), name, parse_arguments(item.get("arguments", "{}"), diagnostics))
        )
    return tuple(calls), tuple(diagnostics)


# ═══════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════


def parse_arguments(value: object, diagnostics: list[str]) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        diagnostics.append("tool arguments were not valid JSON")
        return {}
    if not isinstance(parsed, dict):
        diagnostics.append("tool arguments were not an object")
        return {}
    return parsed


def json_item(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, dict) else {"value": dumped}
    return {"type": str(getattr(value, "type", "unknown"))}


def usage(response: object) -> ModelUsage:
    usg = getattr(response, "usage", None)
    return ModelUsage(
        prompt_tokens=int(getattr(usg, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usg, "completion_tokens", 0) or 0),
    )


def responses_usage(response: object) -> ModelUsage:
    usg = getattr(response, "usage", None)
    return ModelUsage(
        prompt_tokens=int(getattr(usg, "input_tokens", 0) or 0),
        completion_tokens=int(getattr(usg, "output_tokens", 0) or 0),
    )


async def response_cost(response: object, model_id: str) -> float:
    hidden = getattr(response, "_hidden_params", None)
    if isinstance(hidden, dict) and isinstance(hidden.get("response_cost"), (int, float)):
        return float(hidden["response_cost"])
    usg = responses_usage(response)
    try:
        return await compute_cost(model_id, usg.prompt_tokens, usg.completion_tokens)
    except Exception:  # noqa: BLE001
        return 0.0


def invalid_output_result(request: ModelRequest, diagnostic: str) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    if request.invalid_output_result is None:
        return None, (diagnostic,)
    try:
        assert request.output_schema is not None
        validate(request.invalid_output_result, request.output_schema)
    except (AssertionError, ValidationError):
        return None, (diagnostic, "configured invalid-output fallback did not match schema")
    return request.invalid_output_result, (diagnostic, "returned configured no_action fallback")


def is_structured_output_error(error: Any) -> bool:
    text = str(error).lower()
    return "response_format" in text or "structured" in text or "unsupported" in text
