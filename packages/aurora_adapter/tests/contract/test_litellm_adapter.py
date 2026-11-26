"""真实 SDK 与模拟 HTTP 响应验证；不访问供应商、不需要真实密钥。"""

import asyncio
import json
from copy import deepcopy
from typing import TYPE_CHECKING, cast

import httpx
import pytest
from aurora_adapter.model import (
    ChatCapabilities,
    ChatRequest,
    ModelConfig,
    ModelError,
    ModelProtocolError,
    ToolCall,
    UnsupportedCapability,
    collect_response,
)
from aurora_adapter.model.config import resolve_model
from aurora_adapter.model.plugin import create_client, plugin
from aurora_adapter.model.usage import usage_scope
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import register_plugins
from aurora_core.json_data import decode_json, encode_json

if TYPE_CHECKING:
    from aurora_adapter.model.litellm import LiteLLMClient


@pytest.fixture
def sdk(monkeypatch):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm

    return litellm


def request() -> ChatRequest:
    return {"messages": [{"role": "user", "content": "计算"}]}


def response(*, content="回答", calls=None, reason="stop"):
    return {
        "id": "response-test",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "tool_calls": calls},
                "finish_reason": reason,
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def delta(*, content=None, calls=None, reason=None):
    return {"choices": [{"index": 0, "delta": {"content": content, "tool_calls": calls}, "finish_reason": reason}]}


def part(index, *, call_id=None, name=None, arguments=None):
    return {"index": index, "id": call_id, "function": {"name": name, "arguments": arguments}}


class Stream:
    def __init__(self, values, *, error=None, wait=False):
        self.values = iter(values)
        self.error = error
        self.wait = wait
        self.closed = False
        self.waiting = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.values)
        except StopIteration:
            pass
        if self.error:
            raise self.error
        if self.wait:
            self.waiting.set()
            await asyncio.Event().wait()
        raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


def mock_completion(monkeypatch, sdk, value):
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(sdk, "acompletion", complete)
    return calls


@pytest.mark.parametrize("streaming", [False, True])
def test_image_download_rejection_recovers_once_without_mutating_history(sdk, streaming, caplog):
    from aurora_adapter.model.litellm import LiteLLMClient

    unavailable = "https://cdn.example/expired.jpg?rkey=private-signature"
    available = "https://cdn.example/available.jpg"
    history: ChatRequest = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "核对图片；不可读时说明"},
                    {"type": "image_url", "image_url": {"url": unavailable}},
                    {"type": "image_url", "image_url": {"url": available}},
                ],
            }
        ]
    }
    original = deepcopy(history)
    sent = []

    def handle(request):
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "type": "invalid_request_error",
                        "message": f".messages[0].image[0]: Failed to download image from {unavailable} (request_id: secret)",
                    }
                },
            )
        parts = body["messages"][0]["content"]
        assert parts[0] == original["messages"][0]["content"][0]
        assert parts[1]["type"] == "text" and "图片未读取" in parts[1]["text"]
        assert parts[2]["image_url"]["url"] == available
        if streaming:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content="".join(
                    f"data: {json.dumps(value)}\n\n" for value in (delta(content="说明"), delta(reason="stop"))
                )
                + "data: [DONE]\n\n",
            )
        return httpx.Response(200, json=response(content="说明"))

    async def scenario():
        client = LiteLLMClient(
            ModelConfig("deepseek/deepseek-flash", "https://model.test/v1"),
            api_key="test-only",
            transport=httpx.MockTransport(handle),
        )
        try:
            for _ in range(2):
                if streaming:
                    async with client.stream(history) as chunks:
                        result = await collect_response(chunks)
                else:
                    result = await client.complete(history)
                assert result["text"] == "说明" and history == original
            assert len(sent) == 3
        finally:
            await client.aclose()
        assert client._transport.is_closed()

    asyncio.run(scenario())
    own_logs = "\n".join(record.getMessage() for record in caplog.records if record.name.startswith("aurora_"))
    assert "image_download_failed" in own_logs and "private-signature" not in own_logs


def test_image_failure_after_partial_stream_is_not_replayed(sdk, monkeypatch):
    url = "https://cdn.example/failed.jpg"
    error = sdk.BadRequestError(
        message=f"Failed to download image from {url}", model="gpt-4o-mini", llm_provider="openai"
    )
    stream = Stream([delta(content="部分输出")], error=error)
    calls = mock_completion(monkeypatch, sdk, stream)

    async def scenario():
        client = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")
        try:
            with pytest.raises(ModelError, match="无法下载"):
                async with client.stream(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "image_url", "image_url": {"url": url}},
                                ],
                            }
                        ]
                    }
                ) as chunks:
                    assert await anext(chunks) == {"type": "text", "text": "部分输出"}
                    await anext(chunks)
            assert len(calls) == 1 and stream.closed
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_image_recovery_has_one_retry_and_does_not_retry_unmatched_urls(sdk, monkeypatch):
    calls = []
    urls = ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"]

    async def reject(**kwargs):
        calls.append(kwargs)
        raise sdk.BadRequestError(
            message=f"Failed to download image from {urls[min(len(calls) - 1, 1)]}",
            model="gpt-4o-mini",
            llm_provider="openai",
        )

    monkeypatch.setattr(sdk, "acompletion", reject)

    async def scenario():
        client = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")
        try:
            with pytest.raises(ModelError):
                async with client.stream(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": [{"type": "image_url", "image_url": {"url": url}} for url in urls],
                            }
                        ]
                    }
                ) as chunks:
                    await collect_response(chunks)
            assert len(calls) == 2
            with pytest.raises(ModelError):
                await client.complete(request())
            assert len(calls) == 3
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("provider", ["openai", "deepseek"])
def test_real_sdk_preserves_files_and_thinking_across_tool_roundtrip(sdk, streaming, provider, caplog):
    caplog.set_level("INFO", logger="aurora_adapter.model.usage")
    sent = []
    streams = []
    call = {"id": "lookup-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}
    usage = {
        "prompt_tokens": 11,
        "completion_tokens": 5,
        "total_tokens": 16,
        "prompt_tokens_details": {"cached_tokens": 4},
        "completion_tokens_details": {"reasoning_tokens": 2},
    }

    def handle(incoming):
        body = json.loads(incoming.content)
        sent.append(body)
        assert body["thinking"] == {"type": "enabled"}
        assert body["reasoning_effort"] == "high"
        assert body["messages"][0]["content"][1]["image_url"]["url"] == "data:image/png;base64,eA=="
        assert body["messages"][0]["content"][2]["file"]["file_data"] == "data:application/pdf;base64,eA=="
        if len(sent) == 2:
            assert body["messages"][1]["reasoning_content"] == "先检查文件，再查工具"
        if not streaming:
            value = response(
                content="" if len(sent) == 1 else "完成",
                calls=[call] if len(sent) == 1 else None,
                reason="tool_calls" if len(sent) == 1 else "stop",
            )
            value["choices"][0]["message"]["reasoning_content"] = "先检查文件，再查工具"
            value["usage"] = usage
            return httpx.Response(200, json=value)
        thinking = delta()
        thinking["choices"][0]["delta"]["reasoning_content"] = "先检查文件，再查工具"
        values = [
            thinking,
            delta(calls=[{"index": 0, **call}]) if len(sent) == 1 else delta(content="完成"),
            delta(reason="tool_calls" if len(sent) == 1 else "stop"),
            {"choices": [], "usage": usage},
            {"choices": [], "usage": usage},
        ]
        body = "".join(
            "data: "
            + json.dumps({"id": "r", "created": 1, "object": "chat.completion.chunk", "model": "private-model", **item})
            + "\n\n"
            for item in values
        )

        class WireStream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                data = (body + "data: [DONE]\n\n").encode()
                for offset in range(0, len(data), 17):
                    yield data[offset : offset + 17]

            async def aclose(self):
                self.closed = True

        wire = WireStream()
        streams.append(wire)
        return httpx.Response(200, stream=wire, headers={"content-type": "text/event-stream"})

    async def scenario():
        client = cast(
            "LiteLLMClient",
            await create_client(
                ModelConfig(
                    "private-model",
                    "https://model.test/v1",
                    provider=provider,
                    capabilities=ChatCapabilities(True, True),
                    thinking={"type": "enabled"},
                    reasoning_effort="high",
                ),
                api_key="test-only",
            ),
        )
        await client._transport._client.aclose()
        client._transport._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handle), event_hooks={"response": [client._observe_usage]}
        )
        value: ChatRequest = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "检查"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}},
                        {
                            "type": "file",
                            "file": {"filename": "sample.pdf", "file_data": "data:application/pdf;base64,eA=="},
                        },
                    ],
                }
            ],
            "tools": [{"name": "lookup", "description": "检查", "parameters": {"type": "object"}}],
        }
        try:
            for turn in range(2):
                with usage_scope("summary" if turn == 0 else "inference", run_id="usage-run"):
                    if streaming:
                        async with client.stream(value) as chunks:
                            result = await collect_response(chunks)
                    else:
                        result = await client.complete(value)
                assert result["reasoning_content"] == "先检查文件，再查工具"
                if turn == 0:
                    assert result["text"] == "" and result["tool_calls"][0]["id"] == "lookup-1"
                    value["messages"].extend(
                        [
                            {
                                "role": "assistant",
                                "content": result["text"],
                                "tool_calls": result["tool_calls"],
                                "reasoning_content": result["reasoning_content"],
                            },
                            {"role": "tool", "tool_call_id": "lookup-1", "content": "已检查"},
                        ]
                    )
                else:
                    assert result["text"] == "完成"
        finally:
            await client.aclose()
        assert len(sent) == 2
        assert all(stream.closed for stream in streams)
        records = [
            json.loads(item.message.removeprefix("模型用量 "))
            for item in caplog.records
            if item.name == "aurora_adapter.model.usage"
        ]
        assert [item["purpose"] for item in records] == ["summary", "inference"]
        assert all(item["run_id"] == "usage-run" and item["status"] == "completed" for item in records)
        assert all(
            item["usage_reported"]
            and item["tokens"]
            == {
                "input_tokens": 11,
                "output_tokens": 5,
                "total_tokens": 16,
                "cached_input_tokens": 4,
                "reasoning_tokens": 2,
            }
            for item in records
        )
        assert all(
            "test-only" not in item.message and "先检查文件" not in item.message
            for item in caplog.records
            if item.name == "aurora_adapter.model.usage"
        )

    asyncio.run(scenario())


def test_signed_and_redacted_thinking_stream_is_preserved(sdk, monkeypatch):
    def thought(block=None, text=None):
        value = delta()
        value["choices"][0]["delta"].update(reasoning_content=text, thinking_blocks=block)
        return value

    signed = {"type": "thinking", "thinking": "先分析", "signature": "signature-one"}
    redacted = {"type": "redacted_thinking", "data": "opaque-data"}
    stream = Stream(
        [
            thought([{"type": "thinking", "thinking": "先"}], "先"),
            thought([{"type": "thinking", "thinking": "分析"}], "分析"),
            thought([{"type": "thinking", "thinking": "", "signature": "signature-one"}]),
            thought([redacted]),
            delta(content="回答"),
            delta(reason="stop"),
        ]
    )
    calls = mock_completion(monkeypatch, sdk, stream)

    async def scenario():
        client = await create_client(
            ModelConfig("anthropic/claude-sonnet-4-5", thinking={"type": "enabled", "budget_tokens": 2048}),
            api_key="test",
        )
        try:
            async with client.stream(request()) as chunks:
                result = await collect_response(chunks)
            assert result == {
                "text": "回答",
                "reasoning_content": "先分析",
                "thinking_blocks": [signed, redacted],
                "tool_calls": [],
                "finish_reason": "stop",
            }
            assert calls[0]["thinking"] == {"type": "enabled", "budget_tokens": 2048}
        finally:
            await client.aclose()
        assert stream.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("provider,model", [("openai", "Qwen/private-deployment"), ("xiaomi_mimo", "mimo-v2.5-pro")])
def test_explicit_provider_preserves_model_and_supports_custom_capabilities(sdk, streaming, provider, model):
    sent = []
    tool: ToolCall = {"id": "call_1", "name": "echo", "arguments": {"text": "验证"}}

    def handle(request):
        value = json.loads(request.content)
        sent.append(value)
        assert request.url.host == "profile.test" and request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer isolated-key"
        assert value["model"] == model and value["tools"][0]["function"]["name"] == "echo"
        call = {"id": "call_1", "type": "function", "function": {"name": "echo", "arguments": '{"text":"验证"}'}}
        if not streaming:
            return httpx.Response(200, json=response(content="", calls=[call], reason="tool_calls"))
        values = [
            delta(calls=[{"index": 0, **call}]),
            delta(reason="tool_calls"),
        ]
        body = (
            "".join(
                "data: "
                + json.dumps({"id": "r", "created": 1, "object": "chat.completion.chunk", "model": model, **item})
                + "\n\n"
                for item in values
            )
            + "data: [DONE]\n\n"
        )
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    async def scenario():
        client = cast(
            "LiteLLMClient",
            await create_client(
                ModelConfig(
                    model, "https://profile.test/v1", provider=provider, capabilities=ChatCapabilities(True, True)
                ),
                api_key="isolated-key",
            ),
        )
        await client._transport._client.aclose()
        http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        client._transport._client = http
        request = {
            "messages": [{"role": "user", "content": "调用工具"}],
            "tools": [{"name": "echo", "description": "回显", "parameters": {"type": "object"}}],
        }
        try:
            if streaming:
                async with client.stream(cast(ChatRequest, request)) as chunks:
                    result = await collect_response(chunks)
            else:
                result = await client.complete(cast(ChatRequest, request))
            assert result["tool_calls"] == [tool] and result["finish_reason"] == "tool_calls"
            assert len(sent) == 1
        finally:
            await client.aclose()
        assert http.is_closed

    asyncio.run(scenario())


def test_profile_credentials_addresses_and_capabilities_are_isolated(sdk):
    async def scenario():
        clients = []
        transports = []
        sent = []
        try:
            for label, enabled in (("one", True), ("two", False)):
                client = cast(
                    "LiteLLMClient",
                    await create_client(
                        ModelConfig(
                            "team/shared-name",
                            f"https://{label}.test/v1",
                            provider="openai",
                            capabilities=ChatCapabilities(enabled, enabled),
                        ),
                        api_key=f"key-{label}",
                    ),
                )
                clients.append(client)
                await client._transport._client.aclose()

                def handle(request):
                    sent.append(
                        (request.url.host, request.headers["authorization"], json.loads(request.content)["model"])
                    )
                    return httpx.Response(200, json=response())

                http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
                transports.append(http)
                client._transport._client = http
            assert clients[0].capabilities == ChatCapabilities(True, True)
            assert clients[1].capabilities == ChatCapabilities(False, False)
            assert not sdk.supports_function_calling("team/shared-name", custom_llm_provider="openai")
            await clients[0].complete(request())
            await clients[0].aclose()
            assert transports[0].is_closed and not transports[1].is_closed
            with pytest.raises(UnsupportedCapability):
                async with clients[1].stream(request()):
                    pytest.fail("显式禁用流式应拒绝")
            await clients[1].complete(request())
            assert sent == [
                ("one.test", "Bearer key-one", "team/shared-name"),
                ("two.test", "Bearer key-two", "team/shared-name"),
            ]
        finally:
            for client in clients:
                await client.aclose()
        assert all(http.is_closed for http in transports)

    asyncio.run(scenario())


def test_explicit_provider_retains_catalog_defaults_and_unknown_capabilities_stay_disabled(sdk):
    async def scenario():
        for model, capabilities in (
            ("gpt-4o-mini", ChatCapabilities(True, True)),
            ("team/unknown", ChatCapabilities(False, False)),
        ):
            client = await create_client(ModelConfig(model, provider="openai"), api_key="test-only")
            try:
                assert client.capabilities == capabilities
            finally:
                await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["openai", "deepseek"])
def test_registered_factory_uses_real_sdk_and_maps_tool_history(sdk, provider):
    registry = bootstrap()
    register_plugins(registry, (plugin(),))
    resolved = resolve_model(
        registry,
        {
            "main": {
                "adapter": "org.aurora.adapter:adapters/model/litellm/chat",
                "model": "openai/gpt-4o-mini" if provider == "openai" else "deepseek/deepseek-flash",
            }
        },
        {"reasoning": "main"},
        "reasoning",
    )
    sent = []
    call: ToolCall = {"id": "call_1", "name": "add", "arguments": {"a": 1}}

    def handle(value):
        sent.append(json.loads(value.content))
        if provider == "deepseek":
            assert value.url.host == "api.deepseek.com"
            assert "thinking" not in sent[-1]
        return httpx.Response(200, json=response())

    async def scenario():
        client = cast("LiteLLMClient", await resolved.factory(resolved.config, api_key="test-only"))
        # 直接替换测试实例的传输，真实 LiteLLM 与 OpenAI SDK 转换仍参与执行。
        await client._transport._client.aclose()
        http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        client._transport._client = http
        value = request()
        value["tools"] = [{"name": "add", "description": "求和", "parameters": {"type": "object"}}]
        value["messages"] += [
            {"role": "assistant", "content": "", "tool_calls": [call]},
            {"role": "tool", "content": "1", "tool_call_id": "call_1"},
        ]
        before = deepcopy(value)
        try:
            result = await client.complete(value)
            assert result == {"text": "回答", "tool_calls": [], "finish_reason": "stop"}
            assert decode_json(encode_json(result)) == result
            assert value == before
            assert sent[0]["tools"][0]["function"] == value["tools"][0]
            outgoing = sent[0]["messages"][1]["tool_calls"][0]
            assert outgoing["id"] == "call_1" and json.loads(outgoing["function"]["arguments"]) == {"a": 1}
        finally:
            await client.aclose()
        assert http.is_closed

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["openai", "anthropic", "deepseek"])
def test_real_sdk_streaming_and_owned_transport_close(sdk, provider):
    if provider != "anthropic":
        model = "openai/gpt-4o-mini" if provider == "openai" else "deepseek/deepseek-flash"
        values = [
            {"id": "r", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o-mini", **item}
            for item in [delta(content="一"), delta(content="二"), delta(reason="stop")]
        ]
        body = "".join(f"data: {json.dumps(item)}\n\n" for item in values) + "data: [DONE]\n\n"
    else:
        model = "anthropic/claude-sonnet-4-5"
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": model.split("/")[1],
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 0},
                },
            },
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "一二"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
            {"type": "message_stop"},
        ]
        body = "".join(f"event: {item['type']}\ndata: {json.dumps(item)}\n\n" for item in events)

        for event in events:
            if "index" in event:
                event["index"] = 2
        events[1:1] = [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "分析"}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "signed-value"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "redacted_thinking", "data": "opaque-value"},
            },
            {"type": "content_block_stop", "index": 1},
        ]
        body = "".join(f"event: {item['type']}\ndata: {json.dumps(item)}\n\n" for item in events)

    sent = []

    def handle(value):
        sent.append(json.loads(value.content))
        assert value.url.host == "model.test"
        if provider == "deepseek":
            assert "thinking" not in json.loads(value.content)
        if provider == "anthropic" and len(sent) == 2:
            blocks = sent[-1]["messages"][1]["content"]
            assert blocks[:2] == [
                {"type": "thinking", "thinking": "分析", "signature": "signed-value"},
                {"type": "redacted_thinking", "data": "opaque-value"},
            ]
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    async def scenario():
        client = cast(
            "LiteLLMClient",
            await create_client(
                ModelConfig(
                    model,
                    "https://model.test/v1",
                    thinking={"type": "enabled", "budget_tokens": 2048} if provider == "anthropic" else None,
                ),
                api_key="test-only",
            ),
        )
        transport = client._transport
        original = transport._client if provider in ("openai", "deepseek") else transport.client
        await original.aclose()
        http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        transport._client = http
        try:
            async with client.stream(request()) as chunks:
                result = await collect_response(chunks)
            assert result["text"] == "一二" and result["tool_calls"] == [] and result["finish_reason"] == "stop"
            if provider == "anthropic":
                assert result["reasoning_content"] == "分析"
                history = request()
                history["messages"].extend(
                    [
                        {
                            "role": "assistant",
                            "content": result["text"],
                            "reasoning_content": result["reasoning_content"],
                            "thinking_blocks": result["thinking_blocks"],
                        },
                        {"role": "user", "content": "继续"},
                    ]
                )
                async with client.stream(history) as chunks:
                    assert await collect_response(chunks) == result
        finally:
            await client.aclose()
        assert http.is_closed

    asyncio.run(scenario())


def test_interleaved_tool_fragments_are_complete_and_sorted(sdk, monkeypatch):
    stream = Stream(
        [
            delta(content="检查", calls=[part(1, call_id="b", name="se", arguments='{"b":')]),
            delta(
                calls=[part(0, call_id="a", name="first", arguments='{"a":1}'), part(1, name="cond", arguments="2}")]
            ),
            delta(reason="tool_calls"),
            delta(),
            {"choices": [], "usage": {"total_tokens": 4}},
        ]
    )
    calls = mock_completion(monkeypatch, sdk, stream)

    async def scenario():
        client = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")
        try:
            async with client.stream(request()) as chunks:
                assert await anext(chunks) == {"type": "text", "text": "检查"}
                result = await collect_response(chunks)
            assert result["tool_calls"] == [
                {"id": "a", "name": "first", "arguments": {"a": 1}},
                {"id": "b", "name": "second", "arguments": {"b": 2}},
            ]
            assert result["finish_reason"] == "tool_calls" and stream.closed
            assert calls[0]["num_retries"] == 0 and calls[0]["caching"] is False
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("arguments", ['{"a":', "[]", '{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'])
@pytest.mark.parametrize("streaming", [True, False])
def test_invalid_tool_arguments_never_escape_as_a_tool_call(sdk, monkeypatch, arguments, streaming):
    value = Stream([delta(calls=[part(0, call_id="a", name="add", arguments=arguments)]), delta(reason="tool_calls")])
    if not streaming:
        value = response(calls=[{"id": "a", "function": {"name": "add", "arguments": arguments}}], reason="tool_calls")
    mock_completion(monkeypatch, sdk, value)

    async def scenario():
        client = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")
        try:
            with pytest.raises(ModelProtocolError):
                if streaming:
                    async with client.stream(request()) as chunks:
                        await anext(chunks)
                else:
                    await client.complete(request())
            if streaming:
                assert isinstance(value, Stream)
                assert value.closed
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "values",
    [
        [delta(content="不完整")],
        [delta(reason="unknown")],
        [delta(reason="stop"), delta(content="结束之后")],
        [delta(reason="tool_calls")],
        [delta(calls=[part(-1, call_id="a", name="add", arguments="{}")]), delta(reason="tool_calls")],
        [
            delta(
                calls=[
                    part(0, call_id="a", name="add", arguments="{}"),
                    part(1, call_id="a", name="add", arguments="{}"),
                ]
            ),
            delta(reason="tool_calls"),
        ],
    ],
)
def test_invalid_stream_termination_or_identity_fails(sdk, monkeypatch, values):
    stream = Stream(values)
    mock_completion(monkeypatch, sdk, stream)

    async def scenario():
        client = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")
        try:
            with pytest.raises(ModelProtocolError):
                async with client.stream(request()) as chunks:
                    await collect_response(chunks)
            assert stream.closed
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ["stop", "length", "content_filter"])
def test_finish_reasons_are_preserved(sdk, monkeypatch, reason):
    mock_completion(monkeypatch, sdk, response(reason=reason))

    async def scenario():
        client = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")
        try:
            assert (await client.complete(request()))["finish_reason"] == reason
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_capability_rejection_precedes_sdk_and_instances_close_independently(sdk, monkeypatch):
    calls = mock_completion(monkeypatch, sdk, response())

    async def scenario():
        first = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")
        second = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")
        cast("LiteLLMClient", first).capabilities = ChatCapabilities(streaming=False, tool_calls=False)
        try:
            with pytest.raises(UnsupportedCapability):
                async with first.stream(request()):
                    pytest.fail("不支持流式")
            with pytest.raises(UnsupportedCapability):
                await first.complete({"messages": [{"role": "tool", "content": "1", "tool_call_id": "a"}]})
            assert not calls
            await first.aclose()
            await first.aclose()
            with pytest.raises(ModelError, match="已关闭"):
                await first.complete(request())
            assert (await second.complete(request()))["text"] == "回答"
        finally:
            await first.aclose()
            await second.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["early", "cancel", "timeout", "consumer_error"])
def test_stream_exit_always_releases_response(sdk, monkeypatch, mode):
    stream = Stream([delta(content="部分")], wait=True)
    mock_completion(monkeypatch, sdk, stream)

    async def scenario():
        client = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")

        async def consume():
            async with client.stream(request()) as chunks:
                assert await anext(chunks) == {"type": "text", "text": "部分"}
                with pytest.raises(ModelError, match="在途"):
                    await client.aclose()
                with pytest.raises(ModelError, match="并发"):
                    await client.complete(request())
                if mode == "early":
                    return
                if mode == "consumer_error":
                    raise ValueError("消费方错误")
                await anext(chunks)

        try:
            if mode == "early":
                await consume()
            elif mode == "consumer_error":
                with pytest.raises(ValueError, match="消费方"):
                    await consume()
            elif mode == "timeout":
                with pytest.raises(TimeoutError):
                    async with asyncio.timeout(0.02):
                        await consume()
            else:
                task = asyncio.create_task(consume())
                await stream.waiting.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert stream.closed
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("timeout", [False, True])
def test_sdk_errors_are_mapped_without_payload_or_credentials(sdk, monkeypatch, streaming, timeout):
    error = (sdk.Timeout if timeout else sdk.AuthenticationError)(
        message="secret-and-request", model="gpt-4o-mini", llm_provider="openai"
    )
    stream = Stream([delta(content="部分")], error=error)
    mock_completion(monkeypatch, sdk, stream if streaming else error)

    async def scenario():
        client = await create_client(ModelConfig("openai/gpt-4o-mini"), api_key="test-only")
        try:
            with pytest.raises(TimeoutError if timeout else ModelError) as caught:
                if streaming:
                    async with client.stream(request()) as chunks:
                        assert await anext(chunks) == {"type": "text", "text": "部分"}
                        await anext(chunks)
                else:
                    await client.complete(request())
            assert "secret-and-request" not in str(caught.value)
            if streaming:
                assert stream.closed
        finally:
            await client.aclose()

    asyncio.run(scenario())
