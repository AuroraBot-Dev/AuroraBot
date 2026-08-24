"""由显式模型端点驱动的 LiteLLM 模型网关。"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

import litellm

from src.ai.openai import openai_tool_name_map, to_openai_messages, to_openai_tools
from src.contracts import ChatMessage, ModelRequest, ToolCall
from src.utils import get_logger

_logger = get_logger(__name__)

type CompletionCaller = Callable[[dict[str, Any]], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class ProviderEndpoint:
    adapter: str
    base_url: str | None
    secret_env: str


@dataclass(frozen=True, slots=True)
class ModelEndpoint:
    provider: str
    model: str


class LiteLLMModelGateway:
    """按 ModelRequest.model 精确选择配置端点，再统一交给 LiteLLM。"""

    def __init__(
        self,
        providers: Mapping[str, ProviderEndpoint],
        endpoints: Mapping[str, ModelEndpoint],
        *,
        caller: CompletionCaller | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("模型请求超时必须大于零")
        self._providers = MappingProxyType(dict(providers))
        self._endpoints = MappingProxyType(dict(endpoints))
        self._caller = caller or _litellm_completion
        self._timeout_seconds = timeout_seconds

    def validate_endpoint(self, endpoint_id: str) -> None:
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise ValueError(f"模型端点尚未配置：{endpoint_id}")
        provider = self._providers.get(endpoint.provider)
        if provider is None:
            raise ValueError(f"模型端点引用了未知 provider：{endpoint.provider}")
        if provider.adapter not in {"litellm", "openai_compatible"}:
            raise ValueError(f"模型端点 {endpoint_id} 使用了尚未实现的 adapter：{provider.adapter}")
        if provider.adapter == "openai_compatible" and provider.base_url is None:
            raise ValueError(f"OpenAI-compatible provider 缺少 base_url：{endpoint.provider}")

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.validate_endpoint(request.model)
        endpoint = self._endpoints[request.model]
        provider = self._providers[endpoint.provider]
        api_key = os.getenv(provider.secret_env)
        if not api_key:
            raise RuntimeError(f"模型密钥环境变量尚未设置：{provider.secret_env}")
        tool_names = openai_tool_name_map(
            (
                *(tool.name for tool in request.tools),
                *(call.name for message in request.messages for call in message.tool_calls),
            )
        )
        parameters: dict[str, Any] = {
            "model": _gateway_model(endpoint, provider),
            "messages": to_openai_messages(request.messages, tool_names),
            "api_key": api_key,
            "timeout": self._timeout_seconds,
        }
        if provider.adapter == "openai_compatible":
            parameters["api_base"] = provider.base_url
        if request.tools:
            parameters["tools"] = to_openai_tools(request.tools, tool_names)
        _logger.debug(
            "模型请求开始 endpoint=%s message_count=%d tool_count=%d",
            request.model,
            len(request.messages),
            len(request.tools),
        )
        try:
            response = await self._caller(parameters)
            result = _assistant_message(
                _response_mapping(response),
                {alias: name for name, alias in tool_names.items()},
            )
        except Exception as error:
            _logger.error("模型请求失败 endpoint=%s error_type=%s", request.model, type(error).__name__)
            raise
        _logger.debug("模型请求完成 endpoint=%s tool_call_count=%d", request.model, len(result.tool_calls))
        return result


def _gateway_model(endpoint: ModelEndpoint, provider: ProviderEndpoint) -> str:
    prefix = "openai" if provider.adapter == "openai_compatible" else endpoint.provider
    return f"{prefix}/{endpoint.model}"


async def _litellm_completion(parameters: dict[str, Any]) -> object:
    response = cast("Awaitable[object]", litellm.acompletion(**parameters))
    return await response


def _response_mapping(response: object) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        return cast("Mapping[str, Any]", response)
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        value = dump()
        if isinstance(value, Mapping):
            return cast("Mapping[str, Any]", value)
    raise RuntimeError("LiteLLM 响应必须是对象")


def _assistant_message(response: Mapping[str, Any], tool_names: Mapping[str, str]) -> ChatMessage:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise RuntimeError("模型响应缺少 choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise RuntimeError("模型响应缺少 assistant message")
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    raw_calls = message.get("tool_calls")
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, list):
        raise RuntimeError("模型响应的 tool_calls 必须是数组")
    calls = tuple(_tool_call(raw, tool_names) for raw in raw_calls)
    return ChatMessage.assistant(text, tool_calls=calls)


def _tool_call(raw: object, tool_names: Mapping[str, str]) -> ToolCall:
    if not isinstance(raw, Mapping):
        raise RuntimeError("模型响应包含无效 Tool call")
    call_id = raw.get("id")
    function = raw.get("function")
    if not isinstance(call_id, str) or not call_id or not isinstance(function, Mapping):
        raise RuntimeError("模型响应包含无效 Tool call")
    name = function.get("name")
    arguments = function.get("arguments", "{}")
    if not isinstance(name, str) or not name:
        raise RuntimeError("模型响应包含无名称 Tool call")
    domain_name = tool_names.get(name)
    if domain_name is None:
        raise RuntimeError(f"模型响应引用了未知 Provider Tool 名称：{name}")
    if isinstance(arguments, str):
        try:
            decoded = json.loads(arguments)
        except json.JSONDecodeError as error:
            raise RuntimeError("模型响应的 Tool 参数不是有效 JSON") from error
    else:
        decoded = arguments
    if not isinstance(decoded, Mapping):
        raise RuntimeError("模型响应的 Tool 参数必须是对象")
    return ToolCall(call_id, domain_name, cast("Mapping[str, Any]", decoded))
