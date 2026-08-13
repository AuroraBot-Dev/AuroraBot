"""角色域基础。

- :class:`RoleHandler`：角色契约（endpoint / capability_baseline / adapt_request / complete）。
- 共享**纯函数**：工具序列化、chat 通道的消息组装、调用封装（ChatCaller）与
  响应解析。每个角色文件在自己的 ``complete`` 中调用它们——角色自包含，
  多样化改造只改对应角色文件。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, cast

import litellm
from litellm import stream_chunk_builder

from src.ai.execution import GatewayError, GatewayState, GenerationTask, TaskManager, _classify_exception
from src.ai.models import compute_cost
from src.ai.providers import missing_credentials_reason, resolve_model
from src.contracts import (
    STRUCTURED_OUTPUT_NAME,
    ModelCapabilityError,
    ModelContinuation,
    ModelGatewayError,
    ModelResult,
    ModelUsage,
    ToolCall,
    ToolDefinition,
)
from src.utils import get_logger

if TYPE_CHECKING:
    import collections.abc

    from src.ai.gateway import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig
    from src.contracts.model import ModelRequest


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    ALIAS_COLLISION = "tool alias collision"
    INVALID_ARGUMENTS = "tool arguments were not valid JSON"
    ARGUMENTS_NOT_OBJECT = "tool arguments were not an object"
    FORBIDDEN_MODEL_PARAM = "调用方禁止传入 model 参数，模型由网关角色统一指定"
    NO_ASSISTANT_MESSAGE = "Chat provider returned no assistant message"


logger = get_logger("aurora.ai.roles")
_PROVIDER_TOOL_NAME_LIMIT = 64
_INVALID_TOOL_NAME = re.compile(r"[^A-Za-z0-9_-]+")


class RoleHandler(ABC):
    """角色契约。

    - ``endpoint``：通道（当前统一 ``chat_completions``）；
    - ``capability_baseline``：角色的能力侧重声明（并入该角色的能力集）；
    - ``adapt_request``：per-role 请求适配钩子（默认原样返回）；
    - ``complete``：完整实现（每个角色文件自包含）。
    """

    endpoint: ClassVar[str]
    capability_baseline: ClassVar[frozenset[str]] = frozenset()

    def adapt_request(self, request: "ModelRequest") -> "ModelRequest":
        """per-role 请求适配：修改预算、参数或校验输入。"""
        return request

    @abstractmethod
    async def complete(
        self,
        gateway: "ModelGatewayService",
        request: "ModelRequest",
        role: "ModelRoleConfig",
        negotiated: frozenset[str],
    ) -> ModelResult:
        """执行一次模型调用并返回规范化结果（角色自包含实现）。"""

    async def embed(
        self,
        gateway: "ModelGatewayService",
        inputs: list[str],
    ) -> list[list[float]]:
        """词嵌入调用；仅 embedding 角色实现。"""
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════
# 工具序列化（共享）
# ═══════════════════════════════════════════════════════════


def provider_tools(
    tools: tuple[ToolDefinition, ...], *, responses: bool
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    definitions: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    for tool in tools:
        alias = _provider_tool_alias(tool.name)
        if alias in aliases:
            raise ModelCapabilityError(_Msg.ALIAS_COLLISION)
        aliases[alias] = tool.name
        aliases.setdefault(tool.name, tool.name)
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


def _provider_tool_alias(name: str) -> str:
    """生成 Provider 可接受且可由模型稳定复述的 Tool 名称。

    非法字符以双下划线（``__``）替换，避免与原始名称中的单下划线歧义
    （如 ``aur.agent.delegate`` → ``aur__agent__delegate`` 不会与
    ``aur_agent_delegate`` 混淆）。
    """
    readable = _INVALID_TOOL_NAME.sub("__", name).strip("_")
    if not readable:
        readable = "tool"
    if readable[0].isdigit():
        readable = f"tool__{readable}"
    if len(readable) <= _PROVIDER_TOOL_NAME_LIMIT:
        return readable
    digest = hashlib.sha256(name.encode()).hexdigest()[:12]
    prefix = readable[: _PROVIDER_TOOL_NAME_LIMIT - len(digest) - 1].rstrip("_")
    return f"{prefix}__{digest}"


def parse_arguments(value: object, diagnostics: list[str]) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        diagnostics.append(_Msg.INVALID_ARGUMENTS)
        return {}
    if not isinstance(parsed, dict):
        diagnostics.append(_Msg.ARGUMENTS_NOT_OBJECT)
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


# ═══════════════════════════════════════════════════════════
# chat 通道共享实现（角色文件在 complete 中调用）
# ═══════════════════════════════════════════════════════════


class ChatCaller:
    """chat_completions 流式调用封装：凭据检查、流式收集与成本跟踪。"""

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
            missing_reason = missing_credentials_reason(self.model)
            if missing_reason is not None:
                raise GatewayError(missing_reason, retryable=False)

            resolved_model, provider_kwargs = resolve_model(self.model)

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
                await _compute_and_track(0, 0, "cancelled")
                raise
            except Exception as exc:
                raise _classify_exception(exc) from exc

            response_stream = cast("collections.abc.AsyncIterable[Any]", response)
            chunks: list = []
            final_usage: Any = None

            try:
                async for chunk in response_stream:
                    chunks.append(chunk)
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        final_usage = chunk.usage
            except asyncio.CancelledError:
                raw_close = getattr(response, "aclose", None)
                if callable(raw_close):
                    close = cast("collections.abc.Callable[[], collections.abc.Awaitable[None]]", raw_close)
                    await close()
                pt = final_usage.prompt_tokens if final_usage else 0
                ct = final_usage.completion_tokens if final_usage else 0
                await _compute_and_track(pt, ct, "cancelled")
                raise

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

        return self.tm.create_task(_stream_and_collect())


def build_chat_kwargs(
    request: "ModelRequest",
    negotiated: frozenset[str],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """组装 chat 请求：messages、litellm kwargs 与工具别名映射（共享函数）。"""
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
    return messages, kwargs, alias_to_name


async def complete_chat_with_fallback(
    caller: ChatCaller,
    messages: list[dict[str, Any]],
    request: "ModelRequest",
    kwargs: dict[str, Any],
    negotiated: frozenset[str],
    capabilities: frozenset[str],
) -> tuple[GenerationTask, Any]:
    """调用 chat 通道；结构化输出不受支持时按 JSON-text fallback 重试（共享函数）。"""
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


def parse_chat_response(
    gateway: "ModelGatewayService",
    request: "ModelRequest",
    role: "ModelRoleConfig",
    negotiated: frozenset[str],
    response: Any,
    task: GenerationTask,
    alias_to_name: dict[str, str],
) -> ModelResult:
    """解析 chat 响应并构造结果（共享函数）。"""
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
# chat 响应解析（共享函数）
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
