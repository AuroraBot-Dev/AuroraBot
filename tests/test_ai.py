from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from src.ai import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint, to_openai_messages, to_openai_tools
from src.contracts import ChatMessage, ModelRequest, ToolCall, ToolDefinition


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
    schema = {"type": "object", "properties": {"value": {"type": "string"}}}
    result = to_openai_tools((ToolDefinition("echo", "Echo text.", schema),))

    assert result == [
        {
            "type": "function",
            "function": {"name": "echo", "description": "Echo text.", "parameters": schema},
        }
    ]


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
