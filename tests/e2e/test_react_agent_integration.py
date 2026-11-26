"""用真实宿主、模型组件与本地工具验证主动 ReAct 的组合及恢复边界。"""

import asyncio
from typing import cast

import pytest
from aurora_adapter.model import ChatRequest, Message, ModelError, ToolDefinition
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_agent.model import ModelCall, ModelCallState
from aurora_agent.model import plugin as model_plugin
from aurora_agent.react import Guidance, ReActAgent
from aurora_agent.react import plugin as react_plugin
from aurora_control import ExecutionPlug, ExecutionRequest, InstanceStateBinding, StateBinding, component_entries
from aurora_core import Id, entry_from, hook_handler
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import STOP, Lifecycle, LifecycleComponent, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService

STATE = Id("dev.react.integration:state/data")
TOOL: ToolDefinition = {
    "name": "add",
    "description": "两个整数相加",
    "parameters": {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
        "additionalProperties": False,
    },
}


def assemble(data_dir, *, fail_tool=False, fail_model=False):
    registry = bootstrap()
    register_plugins(registry, (react_plugin(), model_plugin()))
    install_lifecycle_slots(registry)
    registry.register(RegistryEntry(STATE, "state_key", StateKey(), "test"))
    ctx = Context(registry)
    hooks = HookConnections(registry)

    def fixed(name):
        return InstanceStateBinding(STATE, (("instance_id", "bot"), ("name", name)))

    def transient(name):
        return StateBinding(STATE, (("instance_id", "bot"), ("name", name)))

    agent = ReActAgent(
        ctx,
        hooks,
        instance_id="bot",
        inbox=fixed("inbox"),
        progress=fixed("progress"),
        runtime=fixed("runtime"),
        batch=transient("batch"),
        decision=transient("decision"),
        max_iterations=5,
    )
    history, accepted = fixed("history"), fixed("accepted")
    model_input, model_output, observations = transient("model_input"), transient("model_output"), transient("tools")

    def respond(request: ChatRequest) -> FakeReply:
        if fail_model:
            return FakeReply(("保留部分推理",), error=ModelError("模型失败"))
        if any(message["content"] == "无需行动" for message in request["messages"]):
            return FakeReply()
        if any(message["role"] == "tool" for message in request["messages"]):
            return FakeReply(("结果为 ", "5"))
        return FakeReply(("准备计算",), tool_calls=({"id": "add-1", "name": "add", "arguments": {"a": 2, "b": 3}},))

    client = FakeModel(respond)
    model = ModelCall(ctx, client, request_state=model_input, output_state=model_output, instance_id="model")

    def messages(request) -> list[Message]:
        try:
            return cast(list[Message], history.get(ctx, request))
        except KeyError:
            return []

    async def prepare(request):
        rows = messages(request)
        try:
            ids = cast(list[str], accepted.get(ctx, request))
        except KeyError:
            ids = []
        for item in cast(list[Guidance], agent.batch.get(ctx, request)):
            if item["id"] not in ids:
                rows.append({"role": "user", "content": cast(str, item["payload"])})
                ids.append(item["id"])
        history.set(ctx, request, rows)
        accepted.set(ctx, request, ids)
        model_input.set(ctx, request, {"messages": rows, "tools": [TOOL]})

    async def decide(request):
        response = cast(ModelCallState, model_output.get(ctx, request))
        if response["finish_reason"] not in ("stop", "tool_calls"):
            raise ModelError("模型未形成完整行动决定")
        rows = messages(request)
        if response["text"] or response["tool_calls"]:
            rows.append({"role": "assistant", "content": response["text"], "tool_calls": response["tool_calls"]})
            history.set(ctx, request, rows)
        agent.decision.set(ctx, request, "act" if response["tool_calls"] else "finish")

    async def act(request):
        response = cast(ModelCallState, model_output.get(ctx, request))
        results: list[Message] = []
        for call in response["tool_calls"]:
            if call["name"] != "add":
                raise ValueError("未知本地工具")
            arguments = call["arguments"]
            if set(arguments) != {"a", "b"} or any(type(value) is not int for value in arguments.values()):
                raise ValueError("add 需要两个整数参数")
            if fail_tool:
                raise ValueError("本地工具失败")
            result = cast(int, arguments["a"]) + cast(int, arguments["b"])
            results.append({"role": "tool", "content": str(result), "tool_call_id": call["id"]})
        observations.set(ctx, request, results)

    async def observe(request):
        history.set(ctx, request, [*messages(request), *cast(list[Message], observations.get(ctx, request))])

    for phase, handler in (("prepare", prepare), ("infer", decide), ("act", act), ("observe", observe)):
        definition = Id(f"dev.react.integration:handlers/{phase}")
        registry.register_many(component_entries(definition, handler, handler, provider="test"))
        agent.slots[phase].connect(ExecutionPlug(definition, handler), priority=10)
    model_link = agent.slots["infer"].connect(model.plug)
    assert model_link.slot_states["inbox"] == agent.inbox
    assert model_link.plug.states["input"] == model_input

    @hook_handler("dev.react.integration:handlers/close", slot=STOP)
    async def close():
        # 装配持有模型资源，并明确本示例的中间值保留策略。
        await client.aclose()
        for address in ctx.list(key=STATE):
            if "run_id" in dict(address.location):
                ctx.delete(address.key, location=dict(address.location))

    entry = entry_from(close, provider="test")
    registry.register(entry)
    hooks.connect(STOP, entry.id, slot_instance="model", handler_instance="model")
    storage = StorageService(data_dir)
    host = Lifecycle(
        ctx,
        hooks,
        [LifecycleComponent("model"), LifecycleComponent("bot", depends_on=("model",))],
        persistence=ContextPersistence(ctx, storage.snapshot_store()),
        storage=storage,
    )
    return host, ctx, agent, client, model_output, history


def test_model_tool_guidance_and_reactivation_survive_host_restart(tmp_path):
    async def scenario():
        host, ctx, agent, client, output, _ = assemble(tmp_path)
        request = ExecutionRequest("first")
        await host.start()
        initial = {"sequence": 1, "id": "initial", "payload": "计算 2 加 3"}
        steering = {"sequence": 2, "id": "steering", "payload": "保留已有计算结果"}
        agent.inbox.set(ctx, request, [initial])
        injected = []

        def steer(change):
            if not injected and change.action == "set" and change.value.get("text") == "准备计算":
                injected.append(True)
                agent.inbox.set(ctx, request, [initial, steering])

        subscription = ctx.subscribe(steer, key=STATE, location=dict(output.address(request).location))
        try:
            await host.run(agent.execute, request)
            assert len(client.requests) == 2 and injected == [True]
            assert {str(message["content"]) for message in client.requests[-1]["messages"]} >= {"5", "保留已有计算结果"}
            assert cast(ModelCallState, output.get(ctx, request))["text"] == "结果为 5"
            assert agent.progress.get(ctx, request) == 2
            assert cast(dict, agent.runtime.get(ctx, request))["run_id"] == "first"
            assert client.active_streams == 0 and not client.closed
        finally:
            ctx.unsubscribe(subscription)
            await host.stop()
        assert client.closed

        restored_host, restored_ctx, restored_agent, restored_client, restored_output, restored_history = assemble(
            tmp_path
        )
        next_request = ExecutionRequest("second")
        await restored_host.start()
        try:
            assert restored_agent.pending(next_request) == []
            assert restored_agent.progress.get(restored_ctx, next_request) == 2
            rows = cast(list[Message], restored_history.get(restored_ctx, next_request))
            assert rows[-1]["content"] == "结果为 5"
            restored_agent.inbox.set(
                restored_ctx, next_request, [initial, steering, {"sequence": 3, "id": "idle", "payload": "无需行动"}]
            )
            await restored_host.run(restored_agent.execute, next_request)
            assert restored_agent.progress.get(restored_ctx, next_request) == 3
            assert cast(ModelCallState, restored_output.get(restored_ctx, next_request))["text"] == ""
            assert cast(dict, restored_agent.runtime.get(restored_ctx, next_request))["status"] == "completed"
            assert len(restored_client.requests) == 1
        finally:
            await restored_host.stop()
        assert restored_client.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["tool", "model"])
def test_failure_closes_model_resources_and_persists_terminal_state(tmp_path, failure):
    async def scenario():
        host, ctx, agent, client, output, _ = assemble(
            tmp_path, fail_tool=failure == "tool", fail_model=failure == "model"
        )
        request = ExecutionRequest("failure")
        await host.start()
        try:
            with pytest.raises(ValueError if failure == "tool" else ModelError):
                await host.run(agent.execute, request)
            assert cast(dict, agent.runtime.get(ctx, request))["status"] == "failed"
            if failure == "model":
                assert cast(ModelCallState, output.get(ctx, request))["text"] == "保留部分推理"
            assert client.active_streams == 0
        finally:
            await host.stop()
        assert client.closed
        restored_host, restored_ctx, restored_agent, _, _, _ = assemble(tmp_path)
        await restored_host.start()
        try:
            assert cast(dict, restored_agent.runtime.get(restored_ctx, request))["status"] == "failed"
        finally:
            await restored_host.stop()

    asyncio.run(scenario())
