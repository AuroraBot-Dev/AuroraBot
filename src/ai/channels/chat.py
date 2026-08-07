"""ChatRole：chat_completions 通道的预设角色实现（RFC 0212）。

包含：ChatCaller（原 ModelCaller 的流式调用封装）、chat 通道的调用与
解析、结构化输出 JSON-text fallback。
"""

from __future__ import annotations

import asyncio
import json
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

import litellm
from litellm import stream_chunk_builder
from litellm.utils import token_counter

from src.ai.channels.base import RoleHandler, json_item, parse_arguments, provider_tools
from src.ai.execution import GatewayError, GatewayState, GenerationTask, TaskManager, _classify_exception
from src.ai.models import compute_cost
from src.ai.providers import missing_credentials_reason, resolve_model
from src.contracts import (
    STRUCTURED_OUTPUT_NAME,
    ModelContinuation,
    ModelGatewayError,
    ModelResult,
    ModelUsage,
    ToolCall,
)
from src.utils import get_logger

if TYPE_CHECKING:
    import collections.abc

    from src.ai.gateway import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig
    from src.contracts.model import ModelRequest


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    FORBIDDEN_MODEL_PARAM = "调用方禁止传入 model 参数，模型由网关角色统一指定"
    NO_ASSISTANT_MESSAGE = "Chat provider returned no assistant message"


logger = get_logger("aurora.ai.chat")


class ChatCaller:
    """chat_completions 通道的流式调用封装：凭据检查、流式收集与成本跟踪。"""

    def __init__(
        self,
        model: str,
        role: str,
        task_manager: TaskManager,
        gateway: GatewayState,
    ) -> None:
        self.model = model
        self.role = role
        self.tm = task_manager
        self.gateway = gateway

    def acompletion(  # noqa: C901, PLR0915
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 2048,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> GenerationTask:
        """强制流式对话，返回可 ``await`` 的 :class:`GenerationTask`。

        禁止调用方传入 ``model`` 参数 —— 模型由角色配置统一指定。
        """
        if "model" in kwargs:
            raise PermissionError(_Msg.FORBIDDEN_MODEL_PARAM)

        async def _compute_and_track(
            prompt_tokens: int,
            completion_tokens: int,
            status: str = "completed",
        ) -> float:
            """费用计算第一信息源：models.dev。"""
            try:
                cost = await compute_cost(self.model, prompt_tokens, completion_tokens)
            except Exception:  # noqa: BLE001
                logger.warning("models.dev 费用计算失败 model=%s", self.model)
                cost = 0.0
            await self.gateway.cost_tracker.add(
                {
                    "task_id": None,
                    "role": self.role,
                    "model": self.model,
                    "type": "completion",
                    "status": status,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost": cost,
                }
            )
            return cost

        async def _stream_and_collect() -> tuple[Any, float]:  # noqa: C901, PLR0912, PLR0915
            prompt_tokens = 0

            missing_reason = missing_credentials_reason(self.model)
            if missing_reason is not None:
                raise GatewayError(missing_reason, retryable=False)

            resolved_model, provider_kwargs = resolve_model(self.model)

            try:
                prompt_tokens = token_counter(model=resolved_model, messages=messages)
            except Exception:  # noqa: BLE001
                logger.debug("token_counter failed for model=%s; fallback prompt_tokens=0", resolved_model)

            litellm_kwargs: dict[str, Any] = {
                "model": resolved_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if timeout is not None:
                litellm_kwargs["timeout"] = timeout
            litellm_kwargs.update(provider_kwargs)
            litellm_kwargs.update(kwargs)

            if self.gateway.log_queries:
                logger.debug(
                    "LLM 请求:\n%s",
                    json.dumps(
                        {
                            "role": self.role,
                            "model": self.model,
                            "messages_count": len(messages),
                            "max_tokens": max_tokens,
                            "timeout": timeout,
                            "messages": [
                                {"role": m.get("role", "?"), "content": m.get("content", "<empty>")} for m in messages
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            else:
                logger.debug(
                    "LLM 请求:\n%s",
                    json.dumps(
                        {
                            "role": self.role,
                            "model": self.model,
                            "messages_count": len(messages),
                            "max_tokens": max_tokens,
                            "timeout": timeout,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

            try:
                response = await litellm.acompletion(**litellm_kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _classify_exception(exc) from exc

            response_stream = cast("collections.abc.AsyncIterable[Any]", response)
            chunks: list = []
            final_usage: Any = None
            is_cancelled = False

            try:
                async for chunk in response_stream:
                    chunks.append(chunk)
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        final_usage = chunk.usage
            except asyncio.CancelledError:
                is_cancelled = True

            if not is_cancelled:
                final_response = stream_chunk_builder(chunks, messages=messages)
                pt = final_usage.prompt_tokens if final_usage else 0
                ct = final_usage.completion_tokens if final_usage else 0
                cost = await _compute_and_track(pt, ct, "completed")

                response_text = ""
                try:
                    if final_response is not None:
                        content = final_response.choices[0].message.content  # type: ignore[attr-defined]
                        response_text = str(content) if content is not None else "<empty>"
                except (AttributeError, IndexError, TypeError):
                    pass

                if self.gateway.log_responses:
                    logger.debug(
                        "LLM 响应:\n%s",
                        json.dumps(
                            {"role": self.role, "cost": cost, "text": response_text},
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                else:
                    logger.debug(
                        "LLM 响应:\n%s",
                        json.dumps({"role": self.role, "cost": cost}, ensure_ascii=False, indent=2),
                    )
                return final_response, cost

            # 被取消：记录已生成 token 的费用后继续传播取消
            if final_usage is not None:
                await _compute_and_track(final_usage.prompt_tokens, final_usage.completion_tokens, "cancelled")
            else:
                completion_tokens = sum(len(c.choices[0].delta.content or "") // 4 for c in chunks if c.choices)
                await _compute_and_track(prompt_tokens, completion_tokens, "cancelled")
            raise asyncio.CancelledError

        return self.tm.create_task(_stream_and_collect())


class ChatChannel(RoleHandler):
    """chat_completions 通道的预设角色：低延迟对话、工具调用与结构化输出。"""

    endpoint = "chat_completions"

    async def complete(
        self,
        gateway: "ModelGatewayService",
        request: "ModelRequest",
        role: "ModelRoleConfig",
        negotiated: frozenset[str],
    ) -> ModelResult:
        capabilities = gateway._capabilities_for(request.role)
        messages: list[dict[str, Any]] = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        if request.continuation is not None:
            messages.extend(dict(item) for item in request.continuation.items)
        tool_defs, alias_to_name = provider_tools(request.tools, responses=False)
        kwargs = dict(request.parameters)
        if tool_defs:
            kwargs.update(
                tools=tool_defs,
                tool_choice=request.tool_choice,
                parallel_tool_calls=request.parallel_tool_calls,
            )
        if request.output_schema is not None and "structured_output" in negotiated:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": STRUCTURED_OUTPUT_NAME, "schema": request.output_schema},
            }
        caller = gateway._caller_for(request.role)
        try:
            task, response = await _complete_chat_with_fallback(
                caller, messages, request, kwargs, negotiated, capabilities
            )
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


# ═══════════════════════════════════════════════════════════
# chat 通道解析（原 _parsing chat 部分）
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


def usage(response: object) -> ModelUsage:
    usg = getattr(response, "usage", None)
    return ModelUsage(
        prompt_tokens=int(getattr(usg, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usg, "completion_tokens", 0) or 0),
    )


def is_structured_output_error(error: Any) -> bool:
    text = str(error).lower()
    return "response_format" in text or "structured" in text or "unsupported" in text


async def _complete_chat_with_fallback(
    caller: ChatCaller,
    messages: list[dict[str, Any]],
    request: "ModelRequest",
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
