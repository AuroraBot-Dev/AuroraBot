"""统一模型协议的离线边界：完整工具请求、流结束与资源所有权。"""

import asyncio

import pytest
from aurora_adapter.model import (
    ChatCapabilities,
    ChatClient,
    ChatRequest,
    ModelConfig,
    ModelError,
    ModelFactory,
    ModelProtocolError,
    ResponseBuffer,
    ToolCall,
    UnsupportedCapability,
    collect_response,
)
from aurora_adapter.model.plugin import plugin
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_core.admission import AdmissionStatus, inspect_admissions
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import register_plugins
from aurora_core.json_data import decode_json, encode_json


def request() -> ChatRequest:
    return {"messages": [{"role": "user", "content": "你好"}]}


def test_stream_and_complete_have_same_json_result():
    async def scenario():
        client: ChatClient = FakeModel(lambda _: FakeReply(("你好", "，世界")))
        async with client.stream(request()) as chunks:
            streamed = await collect_response(chunks)
        assert streamed == await client.complete(request())
        assert streamed == {"text": "你好，世界", "tool_calls": [], "finish_reason": "stop"}
        assert decode_json(encode_json(streamed)) == streamed
        await client.aclose()

    asyncio.run(scenario())


def test_complete_tool_call_and_correlated_tool_message():
    call: ToolCall = {"id": "call_1", "name": "add", "arguments": {"a": 1, "b": 2}}

    def respond(value):
        if value["messages"][-1]["role"] == "tool":
            assert value["messages"][-1]["tool_call_id"] == "call_1"
            return FakeReply(("结果是 ", value["messages"][-1]["content"]))
        return FakeReply(tool_calls=(call,))

    async def scenario():
        client = FakeModel(respond)
        value: ChatRequest = request()
        value["tools"] = [{"name": "add", "description": "求和", "parameters": {"type": "object"}}]
        async with client.stream(value) as chunks:
            events = [chunk async for chunk in chunks]
        assert events == [{"type": "tool_call", "tool_call": call}, {"type": "finish", "reason": "tool_calls"}]
        value["messages"].extend(
            [
                {"role": "assistant", "content": "", "tool_calls": [call]},
                {"role": "tool", "content": "3", "tool_call_id": "call_1"},
            ]
        )
        assert (await client.complete(value))["text"] == "结果是 3"
        assert decode_json(encode_json(value)) == value
        await client.aclose()

    asyncio.run(scenario())


def test_nonstreaming_client_rejects_stream_without_silent_fallback():
    async def scenario():
        client = FakeModel(lambda _: FakeReply(("回答",)), capabilities=ChatCapabilities(streaming=False))
        with pytest.raises(UnsupportedCapability, match="流式"):
            async with client.stream(request()):
                pytest.fail("不应打开流")
        assert not client.requests
        assert (await client.complete(request()))["text"] == "回答"
        value: ChatRequest = request()
        value["tools"] = [{"name": "add", "description": "求和", "parameters": {}}]
        with pytest.raises(UnsupportedCapability, match="工具"):
            await client.complete(value)
        value = {"messages": [{"role": "tool", "content": "3", "tool_call_id": "call_1"}]}
        with pytest.raises(UnsupportedCapability, match="工具"):
            await client.complete(value)
        assert client.active_streams == 0
        await client.aclose()

    asyncio.run(scenario())


def test_early_exit_closes_stream_but_keeps_shared_client_open():
    async def scenario():
        client = FakeModel(lambda _: FakeReply(("第一段", "第二段")))
        async with client.stream(request()) as chunks:
            assert await anext(chunks) == {"type": "text", "text": "第一段"}
            assert client.active_streams == 1
        assert client.active_streams == 0 and not client.closed
        assert (await client.complete(request()))["text"] == "第一段第二段"
        await client.aclose()
        await client.aclose()
        with pytest.raises(ModelError, match="已关闭"):
            await client.complete(request())

    asyncio.run(scenario())


def test_stream_failure_preserves_original_error_and_releases_response():
    async def scenario():
        error = ModelError("模拟模型失败")
        client = FakeModel(lambda _: FakeReply(("部分回答",), error=error))
        with pytest.raises(ModelError) as caught:
            async with client.stream(request()) as chunks:
                assert await anext(chunks) == {"type": "text", "text": "部分回答"}
                await anext(chunks)
        assert caught.value is error
        assert client.active_streams == 0
        await client.aclose()

    asyncio.run(scenario())


def test_cancellation_and_timeout_close_response():
    async def scenario():
        client = FakeModel(lambda _: FakeReply(("不会到达",)), delay=60)
        entered = asyncio.Event()

        async def consume():
            async with client.stream(request()) as chunks:
                entered.set()
                await anext(chunks)

        task = asyncio.create_task(consume())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.active_streams == 0
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await client.complete(request())
        assert client.active_streams == 0
        await client.aclose()

    asyncio.run(scenario())


def test_incomplete_duplicate_and_late_chunks_are_rejected():
    buffer = ResponseBuffer()
    buffer.append({"type": "text", "text": "未结束"})
    with pytest.raises(ModelProtocolError, match="缺少结束"):
        buffer.result()
    buffer.append({"type": "finish", "reason": "length"})
    assert buffer.result()["finish_reason"] == "length"
    with pytest.raises(ModelProtocolError, match="结束片段之后"):
        buffer.append({"type": "finish", "reason": "stop"})
    buffer = ResponseBuffer()
    call: ToolCall = {"id": "same", "name": "add", "arguments": {}}
    buffer.append({"type": "tool_call", "tool_call": call})
    with pytest.raises(ModelProtocolError, match="ID 重复"):
        buffer.append({"type": "tool_call", "tool_call": call})


def test_factory_creates_independent_instances_and_plugin_registers_existing_ids():
    from aurora_config import CONFIGURATION
    from aurora_config import plugin as configuration_plugin
    from aurora_core.lifecycle import install_lifecycle_slots

    async def create(config: ModelConfig, *, api_key: str | None = None) -> ChatClient:
        assert api_key == "test-only"
        return FakeModel(lambda _: FakeReply((config.model,)))

    async def scenario():
        factory: ModelFactory = create
        config = ModelConfig("fake")
        first = await factory(config, api_key="test-only")
        second = await factory(config, api_key="test-only")
        await first.aclose()
        assert (await second.complete(request()))["text"] == "fake"
        await second.aclose()
        assert "api_key" not in vars(config)

    asyncio.run(scenario())
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, (configuration_plugin(), plugin()))
    admissions = inspect_admissions(registry)
    assert {item.source for item in admissions if item.status != AdmissionStatus.ACCEPTED} == {CONFIGURATION}
    assert next(item.status for item in admissions if item.source == CONFIGURATION) == AdmissionStatus.UNCONNECTED
