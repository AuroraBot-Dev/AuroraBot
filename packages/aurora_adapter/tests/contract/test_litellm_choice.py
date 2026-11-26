"""以真实 LiteLLM 转换和模拟传输验证类型化选择、错误隔离和独立资源关闭。"""

import asyncio
import json

import httpx
import pytest
from aurora_adapter.model import ModelConfig, ModelError
from aurora_adapter.model.config import resolve_model
from aurora_adapter.model.contract import ChoiceRequest
from aurora_adapter.model.litellm import LiteLLMClient
from aurora_adapter.model.plugin import plugin
from aurora_adapter.model.usage import usage_scope
from aurora_config import plugin as config_plugin
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import register_plugins


def request() -> ChoiceRequest:
    return {"state": {"text": "等待核对"}, "instructions": "是否介入", "criteria": {"observe": "观察", "guide": "介入"}}


def test_jev_choice_uses_typed_endpoint_and_runtime_credential(caplog):
    caplog.set_level("INFO", logger="aurora_adapter.model.usage")

    async def scenario():
        seen = []

        def handle(req):
            seen.append(req)
            assert str(req.url) == "https://decision.test/v1/systemone"
            assert req.headers["authorization"] == "Bearer runtime-secret"
            body = json.loads(req.content)
            assert body == {
                "model": "jev-latest",
                "state": request()["state"],
                "questions": {
                    "decision": {"type": "choice", "instructions": "是否介入", "criteria": request()["criteria"]}
                },
            }
            return httpx.Response(
                200,
                json={
                    "answers": {
                        "decision": {
                            "type": "choice",
                            "choice": "guide",
                            "confidence": 0.01,
                            "probabilities": {"observe": 0.99, "guide": 0.01},
                        }
                    }
                },
            )

        client = LiteLLMClient(
            kind="choice",
            config=ModelConfig("typesafe/jev-latest", "https://decision.test"),
            api_key="runtime-secret",
            transport=httpx.MockTransport(handle),
        )
        try:
            with usage_scope("cadence", decision_id="decision-1"):
                assert await client.choose(request()) == "guide"
            assert len(seen) == 1
        finally:
            await client.aclose()
        assert client._closed
        records = [
            json.loads(item.message.removeprefix("模型用量 "))
            for item in caplog.records
            if item.name == "aurora_adapter.model.usage"
        ]
        assert len(records) == 1 and records[0]["purpose"] == "cadence"
        assert records[0]["decision_id"] == "decision-1"
        assert not records[0]["usage_reported"] and records[0]["tokens"] == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [301, 401, 402, 422, 429, 502])
def test_http_errors_do_not_retry_follow_redirect_or_expose_body(status):
    async def scenario():
        calls = []

        def handle(req):
            calls.append(req)
            return httpx.Response(
                status, text="runtime-secret private-state", headers={"location": "https://other.test"}
            )

        client = LiteLLMClient(
            kind="choice",
            config=ModelConfig("typesafe/jev-latest"),
            api_key="runtime-secret",
            transport=httpx.MockTransport(handle),
        )
        try:
            with pytest.raises(ModelError) as error:
                await client.choose(request())
            assert "模型供应商调用失败" in str(error.value)
            assert "runtime-secret" not in str(error.value) and "private-state" not in str(error.value)
            assert len(calls) == 1
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"answers": []},
        {"answers": {"decision": None}},
        {"answers": {"decision": {"type": "noul", "choice": "guide"}}},
        {"answers": {"decision": {"type": "choice", "choice": "undeclared"}}},
        {"answers": {"decision": {"type": "choice", "choice": 1}}},
    ],
)
def test_malformed_answers_are_not_decisions(body):
    async def scenario():
        client = LiteLLMClient(
            kind="choice",
            config=ModelConfig("typesafe/jev-latest"),
            api_key="secret",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
        )
        try:
            with pytest.raises(ModelError):
                await client.choose(request())
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_cancel_waits_for_transport_cleanup():
    async def scenario():
        entered, cleaned = asyncio.Event(), asyncio.Event()

        async def handle(req):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        client = LiteLLMClient(
            kind="choice",
            config=ModelConfig("typesafe/jev-latest"),
            api_key="secret",
            transport=httpx.MockTransport(handle),
        )
        task = asyncio.create_task(client.choose(request()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
        await client.aclose()

    asyncio.run(scenario())


def test_chat_and_choice_profiles_cannot_be_interchanged():
    registry = bootstrap()
    register_plugins(registry, (config_plugin(), plugin()))
    profiles = {
        "decision": {"adapter": "org.aurora.adapter:adapters/model/litellm/choice", "model": "typesafe/jev-latest"},
        "chat": {"adapter": "org.aurora.adapter:adapters/model/litellm/chat", "model": "test"},
    }
    bindings = {"cadence": "decision", "reasoning": "chat"}
    assert resolve_model(registry, profiles, bindings, "cadence", kind="choice").profile_name == "decision"
    with pytest.raises(TypeError):
        resolve_model(registry, profiles, bindings, "cadence")
    with pytest.raises(TypeError):
        resolve_model(registry, profiles, bindings, "reasoning", kind="choice")


def test_openai_decisions_translation_and_independent_transports(monkeypatch, caplog):
    caplog.set_level("INFO", logger="aurora_adapter.model.usage")
    from litellm.llms.custom_httpx import llm_http_handler

    def reject_global_client(*args, **kwargs):
        raise AssertionError("不得使用 SDK 全局连接池")

    monkeypatch.setattr(llm_http_handler, "get_async_httpx_client", reject_global_client)

    async def scenario():
        seen = []

        def handle(req):
            body = json.loads(req.content)
            seen.append(req)
            assert str(req.url) == "https://decision.test/v1/decisions"
            assert body["model"] == "gpt-6-luna"
            assert json.loads(body["input"]) == request()["state"]
            assert body["questions"][0]["choices"] == [
                {"value": "observe", "description": "观察"},
                {"value": "guide", "description": "介入"},
            ]
            return httpx.Response(
                200,
                json={
                    "model": "gpt-6-luna",
                    "answers": [
                        {
                            "type": "choice",
                            "name": "decision",
                            "choice": "guide",
                            "confidence": 0.9,
                            "probabilities": [
                                {"value": "observe", "probability": 0.1},
                                {"value": "guide", "probability": 0.9},
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 20, "output_tokens": 0, "total_tokens": 20},
                },
            )

        first = LiteLLMClient(
            kind="choice",
            config=ModelConfig("openai/gpt-6-luna", "https://decision.test/v1"),
            api_key="first",
            transport=httpx.MockTransport(handle),
        )
        second = LiteLLMClient(
            kind="choice",
            config=ModelConfig("openai/gpt-6-luna", "https://decision.test/v1"),
            api_key="second",
            transport=httpx.MockTransport(handle),
        )
        first_http, second_http = first._transport.client, second._transport.client
        try:
            assert await first.choose(request()) == "guide"
            await first.aclose()
            assert first_http.is_closed and not second_http.is_closed
            with pytest.raises(ModelError, match="关闭"):
                await first.choose(request())
            assert await second.choose(request()) == "guide"
            assert [req.headers["authorization"] for req in seen] == ["Bearer first", "Bearer second"]
        finally:
            await first.aclose()
            await second.aclose()
        assert second_http.is_closed
        records = [
            json.loads(item.message.removeprefix("模型用量 "))
            for item in caplog.records
            if item.name == "aurora_adapter.model.usage"
        ]
        assert len(records) == 2 and all(item["purpose"] == "choice" for item in records)
        assert all(item["tokens"] == {"input_tokens": 20, "output_tokens": 0, "total_tokens": 20} for item in records)

    asyncio.run(scenario())
