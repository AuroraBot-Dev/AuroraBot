"""验证模型组件通过 ctx 更新同一输出，保留部分结果并正确结束响应资源。"""

import asyncio

import pytest
from aurora_adapter.model import ChatCapabilities, ModelError, ToolCall, UnsupportedCapability
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_agent.model import ModelCall
from aurora_agent.model import plugin as model_plugin
from aurora_control import CONTROL_STATE, ExecutionRequest, ExecutionSlot, Serial, StateBinding, plugin
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.json_data import encode_json
from aurora_core.registry import RegistryEntry

INPUT = Id("dev.model:state/input")
OUTPUT = Id("dev.model:state/output")


@pytest.fixture
def runtime():
    registry = bootstrap()
    register_plugins(registry, (plugin(), model_plugin()))
    for key in (INPUT, OUTPUT):
        registry.register(RegistryEntry(key, "state_key", StateKey(), "model_test"))
    ctx = Context(registry)
    hooks = HookConnections(registry)
    yield ctx, hooks
    hooks.close()
    ctx.close()


def assemble(ctx, hooks, client, *, streaming=True):
    input_state = StateBinding(INPUT)
    output_state = StateBinding(OUTPUT, (("instance_id", "model"),))
    component = ModelCall(
        ctx, client, instance_id="model", request_state=input_state, output_state=output_state, streaming=streaming
    )
    slot = ExecutionSlot(Serial.definition_id, hooks, instance_id="root")
    link = slot.connect(component.plug)
    assert link.connection.handler == Id("org.aurora.agent:handlers/model_call/execute")
    assert component.plug.reference == "org.aurora.agent:handlers/model_call.model"
    request = ExecutionRequest("run")
    link.plug.states["input"].set(ctx, request, {"messages": [{"role": "user", "content": "输入"}]})
    return Serial(ctx, slot), request, output_state


def test_model_instances_generate_stable_independent_ids(runtime):
    ctx, _ = runtime
    client = FakeModel(lambda _: FakeReply(("回答",)))
    first = ModelCall(ctx, client, request_state=StateBinding(INPUT), output_state=StateBinding(OUTPUT))
    second = ModelCall(ctx, client, request_state=StateBinding(INPUT), output_state=StateBinding(OUTPUT))
    assert first.instance_id != second.instance_id
    assert first.plug.instance_id == first.plug.instance_id == first.instance_id
    assert first.plug.definition_id == second.plug.definition_id == ModelCall.definition_id
    asyncio.run(client.aclose())


@pytest.mark.parametrize("streaming", [False, True])
def test_reasoning_is_separate_from_answer(runtime, streaming):
    ctx, hooks = runtime
    client = FakeModel(lambda _: FakeReply(("结果",), reasoning=("思考", "片段")))
    component, request, output = assemble(ctx, hooks, client, streaming=streaming)
    asyncio.run(component.execute(request))
    result = output.get(ctx, request)
    assert result["text"] == "结果" and result["reasoning_content"] == "思考片段"
    asyncio.run(client.aclose())


def test_partial_reasoning_remains_on_stream_failure(runtime):
    ctx, hooks = runtime
    client = FakeModel(lambda _: FakeReply(reasoning=("尚未完成",), error=ModelError("断流")))
    component, request, output = assemble(ctx, hooks, client)
    with pytest.raises(ModelError):
        asyncio.run(component.execute(request))
    result = output.get(ctx, request)
    assert result["status"] == "failed" and result["reasoning_content"] == "尚未完成" and result["text"] == ""
    asyncio.run(client.aclose())


def test_stream_updates_one_state_and_does_not_close_shared_client(runtime):
    ctx, hooks = runtime

    async def scenario():
        client = FakeModel(lambda _: FakeReply(("第一段", "第二段")))
        root, request, output = assemble(ctx, hooks, client)
        changes = []
        ctx.subscribe(changes.append, key=OUTPUT)
        assert await root.execute(request) is None
        values = [change.value for change in changes]
        assert [value["text"] for value in values] == ["", "第一段", "第一段第二段", "第一段第二段", "第一段第二段"]
        assert values[-1]["status"] == "completed"
        assert values[-1]["finish_reason"] == "stop"
        assert len(ctx.list(key=OUTPUT)) == 1
        assert ctx.list(key=CONTROL_STATE) == ()
        assert client.requests == [{"messages": [{"role": "user", "content": "输入"}]}]
        assert client.active_streams == 0 and not client.closed
        assert encode_json(output.get(ctx, request))
        await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_partial_text_survives_failure_or_cancellation(runtime, outcome):
    ctx, hooks = runtime

    async def scenario():
        client = FakeModel(
            lambda _: (
                FakeReply(("部分回答",), error=ModelError("失败"))
                if outcome == "failed"
                else FakeReply(("部分回答", "不应收到"))
            )
        )
        root, request, output = assemble(ctx, hooks, client)

        def observe(change):
            if outcome == "cancelled" and change.value["status"] == "running" and change.value["text"] == "部分回答":
                task.cancel()

        ctx.subscribe(observe, key=OUTPUT)
        task = asyncio.create_task(root.execute(request))
        with pytest.raises(ModelError if outcome == "failed" else asyncio.CancelledError):
            await task
        state = output.get(ctx, request)
        assert isinstance(state, dict)
        assert state["text"] == "部分回答" and state["status"] == outcome
        assert state["finish_reason"] is None
        assert client.active_streams == 0 and not client.closed
        assert ctx.list(key=CONTROL_STATE) == ()
        await client.aclose()

    asyncio.run(scenario())


def test_tool_request_is_complete_in_ctx(runtime):
    ctx, hooks = runtime

    async def scenario():
        call: ToolCall = {"id": "call_1", "name": "add", "arguments": {"a": 1, "b": 2}}
        client = FakeModel(lambda _: FakeReply(tool_calls=(call,)))
        root, request, output = assemble(ctx, hooks, client)
        await root.execute(request)
        state = output.get(ctx, request)
        assert isinstance(state, dict)
        assert state["tool_calls"] == [call] and state["finish_reason"] == "tool_calls"
        assert state["status"] == "completed"
        await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [True, False])
def test_nonstreaming_mode_is_explicit(runtime, streaming):
    ctx, hooks = runtime

    async def scenario():
        client = FakeModel(lambda _: FakeReply(("回答",)), capabilities=ChatCapabilities(streaming=False))
        root, request, output = assemble(ctx, hooks, client, streaming=streaming)
        if streaming:
            with pytest.raises(UnsupportedCapability):
                await root.execute(request)
            assert client.requests == []
        else:
            await root.execute(request)
        state = output.get(ctx, request)
        assert isinstance(state, dict)
        assert state["status"] == ("failed" if streaming else "completed")
        await client.aclose()

    asyncio.run(scenario())
