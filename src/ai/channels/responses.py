"""ResponsesRole：responses 通道的预设角色实现（RFC 0212）。

包含 responses 通道的调用与解析（原 _channels/_parsing 的 responses 部分）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

import litellm

from src.ai.channels.base import RoleHandler, json_item, parse_arguments, provider_tools
from src.ai.models import compute_cost
from src.ai.providers import resolve_model
from src.contracts import (
    STRUCTURED_OUTPUT_NAME,
    ModelContinuation,
    ModelGatewayError,
    ModelResult,
    ModelUsage,
    ToolCall,
)

if TYPE_CHECKING:
    from src.ai.gateway import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig
    from src.contracts.model import ModelRequest


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    RESPONSES_REQUEST_FAILED = "Responses request failed: {error_type}: {error}"


class ResponsesChannel(RoleHandler):
    """responses 通道的预设角色：原生输出项、推理内容与复杂推理。"""

    endpoint = "responses"

    async def complete(
        self,
        gateway: "ModelGatewayService",
        request: "ModelRequest",
        role: "ModelRoleConfig",
        negotiated: frozenset[str],
    ) -> ModelResult:
        capabilities = gateway._capabilities_for(request.role)
        inputs: list[dict[str, Any]] = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        if request.continuation is not None:
            inputs.extend(dict(item) for item in request.continuation.items)
        tool_defs, alias_to_name = provider_tools(request.tools, responses=True)
        resolved_model, provider_kwargs = resolve_model(gateway._models[request.role])
        kwargs: dict[str, Any] = {
            "input": inputs,
            "model": resolved_model,
            "max_output_tokens": request.budget.max_output_tokens,
            "timeout": request.budget.timeout_seconds,
            "store": False,
            "parallel_tool_calls": request.parallel_tool_calls,
            **provider_kwargs,
            **request.parameters,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs
            kwargs["tool_choice"] = request.tool_choice
        if "reasoning" in capabilities:
            kwargs["include"] = ["reasoning.encrypted_content"]
        if request.output_schema is not None:
            kwargs["text"] = {
                "format": {"type": "json_schema", "name": STRUCTURED_OUTPUT_NAME, "schema": request.output_schema}
            }
        try:
            response = await litellm.aresponses(**kwargs)
        except Exception as error:
            raise ModelGatewayError(
                _Msg.RESPONSES_REQUEST_FAILED.format(error_type=type(error).__name__, error=error)
            ) from error
        output_items = tuple(json_item(item) for item in getattr(response, "output", []) or [])
        text = str(getattr(response, "output_text", "") or "")
        tool_calls, call_diagnostics = response_tool_calls(output_items, alias_to_name)
        data, output_diagnostics = gateway._normalize_output(text, request, negotiated)
        previous_items = tuple(
            request.continuation.items
            if request.continuation
            else ({"role": msg.role, "content": msg.content} for msg in request.messages)
        )
        continuation = ModelContinuation(role.provider, "responses", (*previous_items, *output_items))
        cost = await response_cost(response, gateway._models[request.role])
        return ModelResult(
            model=gateway._models[request.role],
            negotiated_capabilities=negotiated,
            response_mode="native",
            text=text,
            data=data,
            usage=responses_usage(response),
            cost_usd=cost,
            diagnostics=(*output_diagnostics, *call_diagnostics),
            tool_calls=tool_calls,
            finish_reason=str(getattr(response, "status", "completed") or "completed"),
            continuation=continuation,
        )


# ═══════════════════════════════════════════════════════════
# responses 通道解析（原 _parsing responses 部分）
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
