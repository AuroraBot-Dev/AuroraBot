"""由显式模型端点驱动的 LiteLLM 模型网关。"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import monotonic
from types import MappingProxyType
from typing import Any, cast

import litellm

from aurora_bot.ai.openai import openai_tool_name_map, to_openai_messages, to_openai_tools
from aurora_bot.contracts import ChatMessage, ModelRequest, ToolCall
from aurora_bot.contracts.model_binding import ModelBinding, ProviderDefinition, ai_resource_key
from aurora_bot.utils import get_logger

_logger = get_logger(__name__)

type CompletionCaller = Callable[[dict[str, Any]], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class ProviderEndpoint:
    adapter: str
    base_url: str | None
    secret_env: str
    sdk_provider: str | None = None


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
        timeout_seconds: float = 30.0,
        max_attempts: int = 2,
        total_timeout_seconds: float = 60.0,
        max_tokens: int | None = None,
    ) -> None:
        if timeout_seconds <= 0 or total_timeout_seconds <= 0:
            raise ValueError("模型请求超时必须大于零")
        if max_attempts <= 0:
            raise ValueError("模型请求最大尝试次数必须大于零")
        if total_timeout_seconds < timeout_seconds:
            raise ValueError("模型请求总超时不能小于单次尝试超时")
        if max_tokens is not None and max_tokens <= 0:
            raise ValueError("模型输出预算必须大于零")
        compiled_providers = {
            name: ProviderDefinition(
                ai_resource_key(name, "provider"), value.adapter, value.base_url, value.secret_env, value.sdk_provider
            )
            for name, value in providers.items()
        }
        compiled_endpoints: dict[str, ModelBinding] = {}
        for name, endpoint in endpoints.items():
            provider_key = ai_resource_key(endpoint.provider, "provider")
            provider = compiled_providers.get(str(provider_key))
            if provider is None:
                raise ValueError(f"模型端点引用了未知 provider：{endpoint.provider}")
            compiled_endpoints[name] = ModelBinding(
                ai_resource_key(name, "endpoint"),
                provider,
                endpoint.model,
                timeout_seconds,
                max_attempts,
                total_timeout_seconds,
                max_tokens,
            )
        self._providers = MappingProxyType(compiled_providers)
        self._endpoints = MappingProxyType(compiled_endpoints)
        self._caller = caller or _litellm_completion

    @property
    def providers(self) -> tuple[ProviderDefinition, ...]:
        """公开实际保存的提供方快照，包含未被端点采用的已配置提供方。"""
        return tuple(self._providers[name] for name in sorted(self._providers))

    @property
    def endpoints(self) -> tuple[ModelBinding, ...]:
        """公开真正用于执行的端点快照，不从配置另造描述。"""
        return tuple(self._endpoints[name] for name in sorted(self._endpoints))

    def resolve_endpoint(self, endpoint_id: str) -> ModelBinding:
        """验证端点后返回同一份冻结执行配置。"""
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise ValueError(f"模型端点尚未配置：{endpoint_id}")
        provider = endpoint.provider
        if provider.adapter not in {"litellm", "openai_compatible"}:
            raise ValueError(f"模型端点 {endpoint_id} 使用了尚未实现的 adapter：{provider.adapter}")
        if provider.adapter == "openai_compatible" and provider.base_url is None:
            raise ValueError(f"OpenAI-compatible provider 缺少 base_url：{provider.key}")
        return endpoint

    async def complete(self, request: ModelRequest) -> ChatMessage:
        endpoint = self.resolve_endpoint(request.model)
        if endpoint.ref != request.endpoint.ref:
            raise ValueError("模型请求端点版本与当前网关不一致")
        provider = endpoint.provider
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
            "model": f"{provider.sdk_provider}/{endpoint.model}",
            "messages": to_openai_messages(request.messages, tool_names),
            "api_key": api_key,
            "timeout": endpoint.timeout_seconds,
            "max_retries": 0,
        }
        if endpoint.max_tokens is not None:
            parameters["max_tokens"] = endpoint.max_tokens
        if provider.base_url is not None:
            parameters["api_base"] = provider.base_url
        if request.tools:
            parameters["tools"] = to_openai_tools(request.tools, tool_names)
        _logger.debug(
            "模型请求开始 endpoint={} message_count={} tool_count={}",
            request.model,
            len(request.messages),
            len(request.tools),
        )
        started = monotonic()
        try:
            async with asyncio.timeout(endpoint.total_timeout_seconds):
                response = await self._complete_with_attempts(endpoint, parameters)
        except TimeoutError as error:
            elapsed = monotonic() - started
            _logger.error("模型请求超过总截止时间 endpoint={} elapsed_seconds={:.3f}", request.model, elapsed)
            raise TimeoutError(f"模型请求超过总截止时间：{endpoint.total_timeout_seconds:g} 秒") from error
        except Exception as error:
            elapsed = monotonic() - started
            _logger.error(
                "模型请求失败 endpoint={} error_type={} elapsed_seconds={:.3f}",
                request.model,
                type(error).__name__,
                elapsed,
            )
            raise
        result = _assistant_message(
            _response_mapping(response),
            {alias: name for name, alias in tool_names.items()},
        )
        _logger.debug(
            "模型请求完成 endpoint={} tool_call_count={} elapsed_seconds={:.3f}",
            request.model,
            len(result.tool_calls),
            monotonic() - started,
        )
        return result

    async def _complete_with_attempts(self, endpoint: ModelBinding, parameters: dict[str, Any]) -> object:
        """每次尝试和总期限都采用端点快照中的同一份策略。"""
        endpoint_id = str(endpoint.key)
        for attempt in range(1, endpoint.max_attempts + 1):
            started = monotonic()
            try:
                async with asyncio.timeout(endpoint.timeout_seconds):
                    response = await self._caller(parameters)
            except Exception as error:
                elapsed = monotonic() - started
                if attempt >= endpoint.max_attempts:
                    raise
                _logger.warning(
                    "模型请求尝试失败，准备重试 endpoint={} attempt={} max_attempts={} error_type={} "
                    "elapsed_seconds={:.3f}",
                    endpoint_id,
                    attempt,
                    endpoint.max_attempts,
                    type(error).__name__,
                    elapsed,
                )
                continue
            _logger.debug(
                "模型请求尝试完成 endpoint={} attempt={} max_attempts={} elapsed_seconds={:.3f}",
                endpoint_id,
                attempt,
                endpoint.max_attempts,
                monotonic() - started,
            )
            return response
        raise AssertionError("模型请求尝试循环未返回")


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
