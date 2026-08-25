from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import pytest

from src.ai import (
    LiteLLMModelGateway,
    ModelEndpoint,
    ProviderEndpoint,
    openai_tool_name_map,
    to_openai_messages,
    to_openai_tools,
)
from src.contracts import ChatMessage, ModelRequest, ToolCall, ToolDefinition

PROVIDER_TOOL_NAME_MAX_LENGTH = 64
MODEL_ATTEMPT_TIMEOUT_SECONDS = 0.1
MODEL_MAX_ATTEMPTS = 2


def test_openai_adapter_maps_only_message_role_to_user() -> None:
    messages = (
        ChatMessage.system("system"),
        ChatMessage.message("event"),
        ChatMessage.assistant(tool_calls=(ToolCall("call-1", "clock", {"zone": "UTC"}),)),
        ChatMessage.tool("call-1", "12:00"),
    )

    result = to_openai_messages(messages)

    assert [item["role"] for item in result] == ["system", "user", "assistant", "tool"]
    assert result[2]["tool_calls"][0]["function"]["name"] == "clock"
    assert json.loads(result[2]["tool_calls"][0]["function"]["arguments"]) == {"zone": "UTC"}
    assert result[3]["tool_call_id"] == "call-1"


def test_openai_tool_adapter_preserves_native_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string", "enum": ["one", "two"]}},
        "required": ["value"],
    }
    definition = ToolDefinition("echo", "Echo text.", schema)
    result = to_openai_tools((definition,))

    assert result == [
        {
            "type": "function",
            "function": {"name": "echo", "description": "Echo text.", "parameters": schema},
        }
    ]
    parameters = result[0]["function"]["parameters"]
    assert isinstance(parameters, dict)
    assert isinstance(parameters["properties"], dict)
    assert isinstance(parameters["properties"]["value"]["enum"], list)
    parameters["properties"]["value"]["enum"].append("provider-only")
    assert definition.parameters["properties"]["value"]["enum"] == ("one", "two")


def test_openai_adapter_maps_domain_tool_id_to_provider_safe_name() -> None:
    domain_name = "aur.agent.delegate"
    aliases = openai_tool_name_map((domain_name,))
    alias = aliases[domain_name]

    assert alias != domain_name
    assert re.fullmatch(r"[a-zA-Z0-9_-]+", alias)
    assert "__" in alias
    assert len(alias) <= PROVIDER_TOOL_NAME_MAX_LENGTH
    assert (
        to_openai_tools((ToolDefinition(domain_name, "委派", {"type": "object"}),), aliases)[0]["function"]["name"]
        == alias
    )


def test_litellm_gateway_round_trips_domain_tool_names_in_definitions_history_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain_name = "aur.agent.delegate"
    captured: list[dict[str, Any]] = []

    async def call(parameters: dict[str, Any]) -> dict[str, Any]:
        captured.append(parameters)
        alias = parameters["tools"][0]["function"]["name"]
        assert parameters["messages"][2]["tool_calls"][0]["function"]["name"] == alias
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-next",
                                "type": "function",
                                "function": {"name": alias, "arguments": '{"agent":"builtin.worker"}'},
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setenv("TEST_MODEL_KEY", "secret")
    model = LiteLLMModelGateway(
        {"deepseek": ProviderEndpoint("litellm", None, "TEST_MODEL_KEY")},
        {"quality": ModelEndpoint("deepseek", "deepseek-chat")},
        caller=call,
    )
    response = asyncio.run(
        model.complete(
            ModelRequest(
                "quality",
                (
                    ChatMessage.system("系统"),
                    ChatMessage.message("消息"),
                    ChatMessage.assistant(tool_calls=(ToolCall("call-prior", domain_name, {"agent": "worker"}),)),
                    ChatMessage.tool("call-prior", "完成"),
                ),
                (ToolDefinition(domain_name, "委派", {"type": "object"}),),
            )
        )
    )

    provider_name = captured[0]["tools"][0]["function"]["name"]
    assert re.fullmatch(r"[a-zA-Z0-9_-]+", provider_name)
    assert response.tool_calls[0].name == domain_name


def test_litellm_gateway_uses_explicit_endpoint_and_normalizes_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def call(parameters: dict[str, Any]) -> dict[str, Any]:
        calls.append(parameters)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"id": "call-1", "type": "function", "function": {"name": "echo", "arguments": '{"x": 1}'}},
                        ],
                    }
                }
            ]
        }

    monkeypatch.setenv("TEST_MODEL_KEY", "secret")
    model = LiteLLMModelGateway(
        {"provider": ProviderEndpoint("openai_compatible", "https://example.invalid/v1", "TEST_MODEL_KEY")},
        {"quality": ModelEndpoint("provider", "model-name")},
        caller=call,
    )
    response = asyncio.run(
        model.complete(
            ModelRequest(
                "quality",
                (ChatMessage.system("系统"), ChatMessage.message("消息")),
                (ToolDefinition("echo", "回显", {"type": "object"}),),
            )
        )
    )

    assert response.tool_calls[0].arguments == {"x": 1}
    assert calls[0]["api_base"] == "https://example.invalid/v1"
    assert calls[0]["model"] == "openai/model-name"
    assert calls[0]["messages"][1]["role"] == "user"
    assert calls[0]["api_key"] == "secret"


def test_litellm_gateway_accepts_null_tool_calls_for_text_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def call(_parameters: dict[str, Any]) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "你好！",
                        "tool_calls": None,
                    }
                }
            ]
        }

    monkeypatch.setenv("TEST_MODEL_KEY", "secret")
    model = LiteLLMModelGateway(
        {"provider": ProviderEndpoint("openai_compatible", "https://example.invalid/v1", "TEST_MODEL_KEY")},
        {"default": ModelEndpoint("provider", "model-name")},
        caller=call,
    )

    request = ModelRequest("default", (ChatMessage.system("系统"), ChatMessage.message("你好")))
    response = asyncio.run(model.complete(request))

    assert response.content == "你好！"
    assert response.tool_calls == ()


@pytest.mark.parametrize(
    ("providers", "endpoints", "message"),
    [
        ({}, {}, "尚未配置"),
        ({}, {"default": ModelEndpoint("missing", "model")}, "未知 provider"),
        (
            {"provider": ProviderEndpoint("unknown", None, "KEY")},
            {"default": ModelEndpoint("provider", "model")},
            "尚未实现",
        ),
        (
            {"provider": ProviderEndpoint("openai_compatible", None, "KEY")},
            {"default": ModelEndpoint("provider", "model")},
            "缺少 base_url",
        ),
    ],
)
def test_litellm_gateway_rejects_invalid_endpoint_configuration(
    providers: dict[str, ProviderEndpoint],
    endpoints: dict[str, ModelEndpoint],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        LiteLLMModelGateway(providers, endpoints).validate_endpoint("default")


def test_litellm_gateway_requires_secret_without_calling_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_KEY", raising=False)

    async def caller(_parameters: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("不应调用网络")

    model = LiteLLMModelGateway(
        {"provider": ProviderEndpoint("openai_compatible", "https://example.invalid", "MISSING_KEY")},
        {"default": ModelEndpoint("provider", "model")},
        caller=caller,
    )
    request = ModelRequest("default", (ChatMessage.system("系统"), ChatMessage.message("消息")))

    with pytest.raises(RuntimeError, match="环境变量"):
        asyncio.run(model.complete(request))


def test_litellm_gateway_disables_sdk_retries_and_bounds_aurora_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def caller(parameters: dict[str, Any]) -> dict[str, Any]:
        calls.append(parameters)
        if len(calls) == 1:
            raise TimeoutError("first attempt stalled")
        return {"choices": [{"message": {"role": "assistant", "content": "恢复了", "tool_calls": []}}]}

    monkeypatch.setenv("TEST_MODEL_KEY", "secret")
    model = LiteLLMModelGateway(
        {"provider": ProviderEndpoint("openai_compatible", "https://example.invalid", "TEST_MODEL_KEY")},
        {"default": ModelEndpoint("provider", "model")},
        caller=caller,
        timeout_seconds=MODEL_ATTEMPT_TIMEOUT_SECONDS,
        max_attempts=MODEL_MAX_ATTEMPTS,
        total_timeout_seconds=0.2,
    )

    response = asyncio.run(
        model.complete(ModelRequest("default", (ChatMessage.system("系统"), ChatMessage.message("你好"))))
    )

    assert response.content == "恢复了"
    assert len(calls) == MODEL_MAX_ATTEMPTS
    assert all(call["max_retries"] == 0 for call in calls)
    assert all(call["timeout"] == MODEL_ATTEMPT_TIMEOUT_SECONDS for call in calls)


def test_litellm_gateway_enforces_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def caller(_parameters: dict[str, Any]) -> dict[str, Any]:
        await asyncio.Event().wait()
        raise AssertionError("不可达")

    monkeypatch.setenv("TEST_MODEL_KEY", "secret")
    model = LiteLLMModelGateway(
        {"provider": ProviderEndpoint("openai_compatible", "https://example.invalid", "TEST_MODEL_KEY")},
        {"default": ModelEndpoint("provider", "model")},
        caller=caller,
        timeout_seconds=0.02,
        max_attempts=3,
        total_timeout_seconds=0.03,
    )

    with pytest.raises(TimeoutError, match="总截止时间"):
        asyncio.run(model.complete(ModelRequest("default", (ChatMessage.system("系统"), ChatMessage.message("你好")))))
