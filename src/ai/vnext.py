"""RFC 0005/0008 model gateway with Chat Completions and Responses adapters."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import litellm
from jsonschema import ValidationError, validate

from src.ai.contracts import (
    ModelBudgetError,
    ModelCapabilityError,
    ModelContinuation,
    ModelGatewayError,
    ModelRequest,
    ModelResult,
    ModelUsage,
    ToolCall,
    ToolDefinition,
)
from src.ai.gateway import GatewayError, ModelGateway
from src.ai.providers import ProviderConfig, resolve_model, setup_providers
from src.localhost.configuration import AuroraConfig, ModelRoleConfig
from src.utils.serialization import extract_json_from_text

_FORBIDDEN_PARAMETERS = {
    "model",
    "api_key",
    "api_base",
    "base_url",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "store",
    "previous_response_id",
    "input",
    "messages",
    "include",
    "max_tokens",
    "max_output_tokens",
    "response_format",
    "stream",
    "stream_options",
    "text",
    "timeout",
}


class ModelGatewayService:
    """Capability-negotiating model boundary with serial native Tool Calls."""

    def __init__(self, configuration: AuroraConfig) -> None:
        self._configuration = configuration
        self._models = {
            role: f"{definition.provider}/{definition.model}"
            for role, definition in configuration.model_definitions.items()
        }
        custom_providers = tuple(
            ProviderConfig(
                prefix=provider.id,
                litellm_provider="openai",
                api_base=provider.base_url or "",
                api_key_env=provider.secret_env,
            )
            for provider in configuration.model_providers.values()
            if provider.adapter == "openai_compatible"
        )
        if custom_providers:
            setup_providers(*custom_providers)
        self._gateway = ModelGateway(models=self._models)

    def negotiate(self, request: ModelRequest) -> frozenset[str]:
        role = self._configuration.model_definitions.get(request.role)
        if role is None:
            raise ModelCapabilityError(f"unknown model role: {request.role}")
        if request.retry_policy != "none":
            raise ModelCapabilityError("only retry_policy=none is supported")
        if request.parallel_tool_calls:
            raise ModelCapabilityError("parallel tool calls are unsupported by the first cognitive loop")
        if request.cancel_policy not in {"never", "on_external_activity"}:
            raise ModelCapabilityError("unsupported model cancellation policy")
        forbidden = sorted(_FORBIDDEN_PARAMETERS & request.parameters.keys())
        if forbidden:
            raise ModelCapabilityError(f"model parameters may not override controlled fields: {forbidden}")
        if request.response_mode == "native" and role.endpoint != "responses":
            raise ModelCapabilityError(f"role {request.role} does not use a native Responses endpoint")
        if role.endpoint == "responses" and "native_responses" not in role.capabilities:
            raise ModelCapabilityError(f"role {request.role} lacks native_responses")
        if not request.required_capabilities <= role.capabilities:
            missing = sorted(request.required_capabilities - role.capabilities)
            raise ModelCapabilityError(f"role {request.role} lacks capabilities: {missing}")
        if request.tools and "tools" not in role.capabilities:
            raise ModelCapabilityError(f"role {request.role} lacks tools")
        if request.continuation is not None:
            expected_provider = role.provider
            if request.continuation.provider != expected_provider or request.continuation.channel != role.endpoint:
                raise ModelCapabilityError("model continuation does not match the selected role endpoint")
        negotiated = set(request.required_capabilities)
        if request.tools:
            negotiated.add("tools")
        if role.endpoint == "responses":
            negotiated.add("native_responses")
        if request.output_schema is not None:
            if role.endpoint == "responses" or "structured_output" in role.capabilities:
                negotiated.add("structured_output")
            elif request.allow_json_text_fallback and "json_text_fallback" in role.capabilities:
                negotiated.add("json_text_fallback")
            else:
                raise ModelCapabilityError("structured output is unavailable and JSON-text fallback is not permitted")
        return frozenset(negotiated)

    async def complete(self, request: ModelRequest) -> ModelResult:
        negotiated = self.negotiate(request)
        role = self._configuration.model_definitions[request.role]
        provider = self._configuration.model_providers[role.provider]
        if not os.getenv(provider.secret_env):
            raise ModelGatewayError(f"missing model credential: {provider.secret_env}")
        if role.endpoint == "responses":
            result = await self._complete_responses(request, role, negotiated)
        else:
            result = await self._complete_chat(request, role, negotiated)
        if request.budget.max_cost_usd is not None and result.cost_usd > request.budget.max_cost_usd:
            raise ModelBudgetError("model cost exceeded max_cost_usd")
        return result

    async def _complete_chat(
        self, request: ModelRequest, role: ModelRoleConfig, negotiated: frozenset[str]
    ) -> ModelResult:
        messages: list[dict[str, Any]] = [
            {"role": message.role, "content": message.content} for message in request.messages
        ]
        if request.continuation is not None:
            messages.extend(dict(item) for item in request.continuation.items)
        provider_tools, alias_to_name = _provider_tools(request.tools, responses=False)
        kwargs = dict(request.parameters)
        if provider_tools:
            kwargs.update(
                tools=provider_tools,
                tool_choice=request.tool_choice,
                parallel_tool_calls=False,
            )
        if request.output_schema is not None and "structured_output" in negotiated:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "aurora_result", "schema": request.output_schema},
            }
        caller = self._gateway.use_model(request.role)
        try:
            task, response = await self._complete_chat_with_fallback(caller, messages, request, kwargs, negotiated)
        except GatewayError as error:
            raise ModelGatewayError(str(error)) from error
        message = _chat_message(response)
        text = str(getattr(message, "content", "") or "")
        tool_calls, call_diagnostics = _chat_tool_calls(message, alias_to_name)
        data, output_diagnostics = self._normalize_output(text, request, negotiated)
        assistant_item = _chat_assistant_item(message)
        continuation_items = (
            tuple(request.continuation.items)
            if request.continuation
            else tuple({"role": message.role, "content": message.content} for message in request.messages)
        )
        continuation = ModelContinuation(role.provider, "chat_completions", (*continuation_items, assistant_item))
        finish_reason = str(getattr(response.choices[0], "finish_reason", "stop") or "stop")
        return ModelResult(
            model=self._models[request.role],
            negotiated_capabilities=negotiated,
            response_mode=request.response_mode,
            text=text,
            data=data,
            usage=_usage(response),
            cost_usd=task.cost,
            diagnostics=(*output_diagnostics, *call_diagnostics),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            continuation=continuation,
        )

    async def _complete_chat_with_fallback(
        self,
        caller: Any,
        messages: list[dict[str, Any]],
        request: ModelRequest,
        kwargs: dict[str, Any],
        negotiated: frozenset[str],
    ) -> tuple[Any, Any]:
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
                and "json_text_fallback" in self._configuration.model_definitions[request.role].capabilities
                and _is_structured_output_error(error)
            )
            if not can_fallback:
                raise
            fallback_kwargs = dict(kwargs)
            fallback_kwargs.pop("response_format", None)
            fallback_task = caller.acompletion(
                messages,
                max_tokens=request.budget.max_output_tokens,
                timeout=request.budget.timeout_seconds,
                **fallback_kwargs,
            )
            return fallback_task, await fallback_task

    async def _complete_responses(
        self, request: ModelRequest, role: ModelRoleConfig, negotiated: frozenset[str]
    ) -> ModelResult:
        inputs: list[dict[str, Any]] = [
            {"role": message.role, "content": message.content} for message in request.messages
        ]
        if request.continuation is not None:
            inputs.extend(dict(item) for item in request.continuation.items)
        provider_tools, alias_to_name = _provider_tools(request.tools, responses=True)
        resolved_model, provider_kwargs = resolve_model(self._models[request.role])
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
        if provider_tools:
            kwargs["tools"] = provider_tools
            kwargs["tool_choice"] = request.tool_choice
        if "reasoning" in role.capabilities:
            kwargs["include"] = ["reasoning.encrypted_content"]
        if request.output_schema is not None:
            kwargs["text"] = {
                "format": {"type": "json_schema", "name": "aurora_result", "schema": request.output_schema}
            }
        try:
            response = await litellm.aresponses(**kwargs)
        except Exception as error:
            raise ModelGatewayError(f"Responses request failed: {type(error).__name__}: {error}") from error
        output_items = tuple(_json_item(item) for item in getattr(response, "output", []) or [])
        text = str(getattr(response, "output_text", "") or "")
        tool_calls, call_diagnostics = _response_tool_calls(output_items, alias_to_name)
        data, output_diagnostics = self._normalize_output(text, request, negotiated)
        previous_items = (
            tuple(request.continuation.items)
            if request.continuation
            else tuple({"role": message.role, "content": message.content} for message in request.messages)
        )
        continuation = ModelContinuation(role.provider, "responses", (*previous_items, *output_items))
        return ModelResult(
            model=self._models[request.role],
            negotiated_capabilities=negotiated,
            response_mode="native",
            text=text,
            data=data,
            usage=_responses_usage(response),
            cost_usd=_response_cost(response),
            diagnostics=(*output_diagnostics, *call_diagnostics),
            tool_calls=tool_calls,
            finish_reason=str(getattr(response, "status", "completed") or "completed"),
            continuation=continuation,
        )

    @staticmethod
    def _normalize_output(
        text: str, request: ModelRequest, negotiated: frozenset[str]
    ) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
        if request.output_schema is None:
            return None, ()
        parsed = extract_json_from_text(text)
        if parsed is None:
            return _invalid_output_result(request, "model output did not contain a JSON object")
        try:
            validate(parsed, request.output_schema)
        except ValidationError as error:
            return _invalid_output_result(request, f"model output failed JSON Schema validation: {error.message}")
        mode = "structured_output" if "structured_output" in negotiated else "json_text_fallback"
        return parsed, (f"output mode: {mode}",)


def append_tool_result(
    continuation: ModelContinuation,
    call_id: str,
    result: object,
    *,
    is_error: bool,
) -> ModelContinuation:
    """Append a normalized tool result in the endpoint's replay shape."""
    serialized = json.dumps(
        {"is_error": is_error, "result": result},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if continuation.channel == "responses":
        item = {"type": "function_call_output", "call_id": call_id, "output": serialized}
    else:
        item = {"role": "tool", "tool_call_id": call_id, "content": serialized}
    return ModelContinuation(continuation.provider, continuation.channel, (*continuation.items, item))


def _provider_tools(
    tools: tuple[ToolDefinition, ...], *, responses: bool
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    definitions: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    for tool in tools:
        alias = f"aurora_{hashlib.sha256(tool.name.encode()).hexdigest()[:20]}"
        if alias in aliases:
            raise ModelCapabilityError("tool alias collision")
        aliases[alias] = tool.name
        description = f"Aurora capability {tool.name}. {tool.description}".strip()
        if responses:
            definitions.append(
                {"type": "function", "name": alias, "description": description, "parameters": tool.parameters_schema}
            )
        else:
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": alias,
                        "description": description,
                        "parameters": tool.parameters_schema,
                    },
                }
            )
    return definitions, aliases


def _chat_message(response: object) -> Any:
    try:
        return response.choices[0].message  # type: ignore[attr-defined]
    except (AttributeError, IndexError, TypeError) as error:
        raise ModelGatewayError("Chat provider returned no assistant message") from error


def _chat_assistant_item(message: object) -> dict[str, Any]:
    item: dict[str, Any] = {"role": "assistant", "content": getattr(message, "content", None)}
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning is not None:
        item["reasoning_content"] = reasoning
    calls = getattr(message, "tool_calls", None)
    if calls:
        item["tool_calls"] = [_json_item(call) for call in calls]
    return item


def _chat_tool_calls(message: object, aliases: dict[str, str]) -> tuple[tuple[ToolCall, ...], tuple[str, ...]]:
    calls: list[ToolCall] = []
    diagnostics: list[str] = []
    for raw in getattr(message, "tool_calls", None) or []:
        function = getattr(raw, "function", None)
        alias = str(getattr(function, "name", ""))
        name = aliases.get(alias)
        if name is None:
            diagnostics.append(f"provider returned unknown tool alias: {alias}")
            continue
        arguments = _arguments(getattr(function, "arguments", "{}"), diagnostics)
        calls.append(ToolCall(str(getattr(raw, "id", "")), name, arguments))
    return tuple(calls), tuple(diagnostics)


def _response_tool_calls(
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
        calls.append(ToolCall(str(item.get("call_id", "")), name, _arguments(item.get("arguments", "{}"), diagnostics)))
    return tuple(calls), tuple(diagnostics)


def _arguments(value: object, diagnostics: list[str]) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        diagnostics.append("tool arguments were not valid JSON")
        return {}
    if not isinstance(parsed, dict):
        diagnostics.append("tool arguments were not an object")
        return {}
    return parsed


def _json_item(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, dict) else {"value": dumped}
    return {"type": str(getattr(value, "type", "unknown"))}


def _usage(response: object) -> ModelUsage:
    usage = getattr(response, "usage", None)
    return ModelUsage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _responses_usage(response: object) -> ModelUsage:
    usage = getattr(response, "usage", None)
    return ModelUsage(
        prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def _response_cost(response: object) -> float:
    hidden = getattr(response, "_hidden_params", None)
    if isinstance(hidden, dict) and isinstance(hidden.get("response_cost"), (int, float)):
        return float(hidden["response_cost"])
    try:
        return float(litellm.completion_cost(completion_response=response))
    except Exception:  # noqa: BLE001 - missing price metadata must not fail cognition.
        return 0.0


def _invalid_output_result(request: ModelRequest, diagnostic: str) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    if request.invalid_output_result is None:
        return None, (diagnostic,)
    try:
        assert request.output_schema is not None
        validate(request.invalid_output_result, request.output_schema)
    except (AssertionError, ValidationError):
        return None, (diagnostic, "configured invalid-output fallback did not match schema")
    return request.invalid_output_result, (diagnostic, "returned configured no_action fallback")


def _is_structured_output_error(error: GatewayError) -> bool:
    text = str(error).lower()
    return "response_format" in text or "structured" in text or "unsupported" in text
