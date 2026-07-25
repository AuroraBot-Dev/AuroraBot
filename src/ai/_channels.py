"""模型网关通道调度：Chat Completions / Responses 双通道实现。

本模块包含纯函数，接收 ModelGatewayService 实例作为调度上下文。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import litellm

from src.ai._parsing import (
    chat_assistant_item,
    chat_message,
    chat_tool_calls,
    is_structured_output_error,
    json_item,
    provider_tools,
    response_cost,
    response_tool_calls,
    responses_usage,
    usage,
)
from src.ai.execution import GatewayError, GenerationTask
from src.ai.providers import resolve_model
from src.contracts.model import (
    STRUCTURED_OUTPUT_NAME,
    ModelContinuation,
    ModelGatewayError,
    ModelRequest,
    ModelResult,
)
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.ai.execution import ModelCaller
    from src.ai.vnext import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig

logger = get_logger(__name__)


async def _complete_chat(
    gateway: ModelGatewayService, request: ModelRequest, role: ModelRoleConfig, negotiated: frozenset[str]
) -> ModelResult:
    """Chat Completions 通道：发送消息、解析工具调用和结构化输出。"""
    capabilities = gateway._capabilities_for(request.role)
    messages: list[dict[str, Any]] = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    if request.continuation is not None:
        messages.extend(dict(item) for item in request.continuation.items)
    tool_defs, alias_to_name = provider_tools(request.tools, responses=False)
    kwargs = dict(request.parameters)
    if tool_defs:
        kwargs.update(tools=tool_defs, tool_choice=request.tool_choice, parallel_tool_calls=False)
    if request.output_schema is not None and "structured_output" in negotiated:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": STRUCTURED_OUTPUT_NAME, "schema": request.output_schema},
        }
    caller = gateway.use_model(request.role)
    try:
        task, response = await _complete_chat_with_fallback(caller, messages, request, kwargs, negotiated, capabilities)
    except GatewayError as error:
        raise ModelGatewayError(str(error)) from error
    message = chat_message(response)
    text = str(getattr(message, "content", "") or "")
    tool_calls, call_diagnostics = chat_tool_calls(message, alias_to_name)
    data, output_diagnostics = gateway._normalize_output(text, request, negotiated)
    assistant_item = chat_assistant_item(message)
    previous_items = tuple(
        request.continuation.items
        if request.continuation
        else ({"role": msg.role, "content": msg.content} for msg in request.messages)
    )
    continuation = ModelContinuation(role.provider, "chat_completions", (*previous_items, assistant_item))
    finish_reason = str(getattr(response.choices[0], "finish_reason", "stop") or "stop")
    return ModelResult(
        model=gateway._models[request.role],
        negotiated_capabilities=negotiated,
        response_mode=request.response_mode,
        text=text,
        data=data,
        usage=usage(response),
        cost_usd=task.cost,
        diagnostics=(*output_diagnostics, *call_diagnostics),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        continuation=continuation,
    )


async def _execute_responses_channel(
    gateway: ModelGatewayService, request: ModelRequest, role: ModelRoleConfig, negotiated: frozenset[str]
) -> ModelResult:
    """Responses 通道：调用 litellm.aresponses，解析输出和工具调用。"""
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
        "parallel_tool_calls": False,
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
        raise ModelGatewayError(f"Responses request failed: {type(error).__name__}: {error}") from error
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


async def _complete_chat_with_fallback(
    caller: ModelCaller,
    messages: list[dict[str, Any]],
    request: ModelRequest,
    kwargs: dict[str, Any],
    negotiated: frozenset[str],
    capabilities: frozenset[str],
) -> tuple[GenerationTask, Any]:
    try:
        task = caller.acompletion(
            messages,
            max_tokens=request.budget.max_output_tokens,
            timeout=request.budget.timeout_seconds,
            **kwargs,
        )
        return task, await task
    except GatewayError as error:
        can_fallback = (
            "structured_output" in negotiated
            and request.allow_json_text_fallback
            and "json_text_fallback" in capabilities
            and is_structured_output_error(error)
        )
        if not can_fallback:
            raise
        logger.warning(
            "structured output unsupported; using JSON text fallback model_role=%s error_type=%s",
            request.role,
            type(error).__name__,
        )
        fallback_kwargs = dict(kwargs)
        fallback_kwargs.pop("response_format", None)
        fallback_task = caller.acompletion(
            messages,
            max_tokens=request.budget.max_output_tokens,
            timeout=request.budget.timeout_seconds,
            **fallback_kwargs,
        )
        return fallback_task, await fallback_task
