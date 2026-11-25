"""验证工具选择、参数拒绝、结构化失败、超时与取消收尾。"""

import asyncio
from typing import cast

import pytest
from aurora_adapter.model import ToolDefinition
from aurora_agent.tools import TOOLS, ToolBatchState, ToolExecutor, ToolRejected, ToolSpec, plugin
from aurora_control import ExecutionPlug, ExecutionRequest, StateBinding, component_entries
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.json_data import encode_json
from aurora_core.registry import RegistryEntry

STATE = Id("dev.tools:state/data")
COMPONENT = Id("dev.tools:handlers/add")
TOOL = Id("dev.tools:tools/add")
DEFINITION: ToolDefinition = {
    "name": "add",
    "description": "两个非负整数相加",
    "parameters": {
        "type": "object",
        "properties": {"a": {"type": "integer", "minimum": 0}, "b": {"type": "integer", "minimum": 0}},
        "required": ["a", "b"],
        "additionalProperties": False,
    },
}


@pytest.fixture
def runtime():
    registry = bootstrap()
    register_plugins(registry, (plugin(),))
    registry.register(RegistryEntry(STATE, "state_key", StateKey(), "test"))
    ctx, hooks = Context(registry), HookConnections(registry)
    yield registry, ctx, hooks
    hooks.close()
    ctx.close()


def assemble(runtime, *, behavior="success", timeout=1.0):
    registry, ctx, hooks = runtime

    def binding(name):
        return StateBinding(STATE, (("name", name),))

    executor = ToolExecutor(
        ctx,
        registry,
        hooks,
        request_state=binding("calls"),
        output_state=binding("results"),
        current_state=binding("current"),
        timeout=timeout,
    )
    input_state, output_state = binding("input"), binding("output")
    invocations, cleanups = [], []
    entered = asyncio.Event()

    async def execute(request):
        call = input_state.get(ctx, request)
        assert isinstance(call, dict)
        invocations.append((call, request))
        if behavior == "fail":
            raise RuntimeError("本地工具失败")
        if behavior == "wait":
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleanups.append(call["id"])
        if behavior == "missing":
            return
        output_state.set(
            ctx, request, object() if behavior == "invalid" else call["arguments"]["a"] + call["arguments"]["b"]
        )

    registry.register_many(component_entries(COMPONENT, execute, execute, provider="test"))
    registry.register(RegistryEntry(TOOL, "tool", ToolSpec(COMPONENT, DEFINITION), "test", register_to=TOOLS))
    executor.connect(TOOL, ExecutionPlug(COMPONENT, execute, {"input": input_state, "output": output_state}))
    return executor, invocations, cleanups, entered


def call(identity="call", **changes):
    return {"id": identity, "name": "add", "arguments": {"a": 2, "b": 3}, **changes}


def submit(executor, ctx, calls):
    request = ExecutionRequest("run")
    executor.request_state.set(ctx, request, {"turn_id": "turn", "calls": calls})
    return request


def state(executor, ctx, request):
    return cast(ToolBatchState, executor.output_state.get(ctx, request))


def test_connected_definitions_are_copied_and_execution_uses_ctx(runtime):
    _, ctx, hooks = runtime
    executor, invocations, _, _ = assemble(runtime)
    definitions = executor.definitions()
    definitions[0]["parameters"]["type"] = "string"
    assert executor.definitions() == [DEFINITION]
    request = submit(executor, ctx, [call("one"), call("two")])
    asyncio.run(executor.execute(request))
    result = state(executor, ctx, request)
    assert result["status"] == "completed" and result["turn_id"] == "turn"
    assert [row.get("value") for row in result["results"]] == [5, 5]
    assert [row[0]["id"] for row in invocations] == ["one", "two"]
    assert all(
        child.run_id == request.run_id and child.parent_execution_id == request.execution_id for _, child in invocations
    )
    assert len({child.execution_id for _, child in invocations}) == 2
    hooks.disconnect(executor.slot.links()[0].connection)
    assert executor.definitions() == []
    asyncio.run(executor.execute(request))
    assert all(row.get("error", {})["code"] == "unknown_tool" for row in state(executor, ctx, request)["results"])


@pytest.mark.parametrize("arguments", [{"a": True, "b": 2}, {"a": -1, "b": 2}, {"a": 1}, {"a": 1, "b": 2, "c": 3}])
def test_invalid_arguments_do_not_execute(runtime, arguments):
    _, ctx, _ = runtime
    executor, calls, _, _ = assemble(runtime)
    request = submit(executor, ctx, [call(arguments=arguments)])
    asyncio.run(executor.execute(request))
    assert calls == []
    assert state(executor, ctx, request)["results"][0].get("error", {})["code"] == "invalid_arguments"


@pytest.mark.parametrize(
    "behavior,code",
    [("fail", "tool_failed"), ("missing", "invalid_result"), ("invalid", "invalid_result"), ("wait", "timeout")],
)
def test_tool_errors_become_observations(runtime, behavior, code):
    _, ctx, _ = runtime
    executor, invocations, cleanups, _ = assemble(runtime, behavior=behavior, timeout=0.01)
    request = submit(executor, ctx, [call()])
    # 未写出结果时不能消费上次成功调用留下的值。
    executor.slot.links()[0].plug.states["output"].set(ctx, request, "旧结果")
    asyncio.run(executor.execute(request))
    result = state(executor, ctx, request)
    assert result["status"] == "completed"
    assert result["results"][0].get("error", {})["code"] == code
    assert len(invocations) == 1
    assert cleanups == (["call"] if behavior == "wait" else [])
    assert encode_json([record.value for record in ctx.snapshot().records])


def test_before_rejection_and_after_observation(runtime):
    registry, ctx, _ = runtime
    executor, calls, _, _ = assemble(runtime)
    observed = []

    async def reject(request):
        raise ToolRejected("当前条件不允许执行")

    async def observe(request):
        observed.append(executor.current_state.get(ctx, request))

    for slot, handler, name in ((executor.before, reject, "reject"), (executor.after, observe, "observe")):
        identity = Id(f"dev.tools:handlers/{name}")
        registry.register_many(component_entries(identity, handler, handler, provider="test"))
        slot.connect(ExecutionPlug(identity, handler))
    request = submit(executor, ctx, [call()])
    asyncio.run(executor.execute(request))
    assert calls == []
    assert observed[0]["result"]["error"]["code"] == "rejected"
    assert state(executor, ctx, request)["results"][0].get("error", {})["message"] == "当前条件不允许执行"


def test_cancel_preserves_results_and_does_not_start_later_calls(runtime):
    _, ctx, _ = runtime
    executor, calls, cleanups, entered = assemble(runtime, behavior="wait")
    request = submit(executor, ctx, [call("one"), call("two")])

    async def scenario():
        task = asyncio.create_task(executor.execute(request))
        await entered.wait()
        with pytest.raises(RuntimeError, match="正在运行"):
            await executor.execute(request)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    results = state(executor, ctx, request)
    assert results["status"] == "cancelled"
    assert [row.get("error", {})["code"] for row in results["results"]] == ["cancelled", "not_executed"]
    assert len(calls) == 1 and cleanups == ["one"]
    with pytest.raises(KeyError):
        executor.current_state.get(ctx, request)


def test_duplicate_call_ids_reject_entire_batch(runtime):
    _, ctx, _ = runtime
    executor, calls, _, _ = assemble(runtime)
    request = submit(executor, ctx, [call(), call()])
    with pytest.raises(ValueError):
        asyncio.run(executor.execute(request))
    assert calls == []


def test_after_hook_failure_keeps_completed_side_effect_and_stops_batch(runtime):
    registry, ctx, _ = runtime
    executor, calls, _, _ = assemble(runtime)

    async def broken(request):
        raise RuntimeError("观察扩展失败")

    identity = Id("dev.tools:handlers/broken_after")
    registry.register_many(component_entries(identity, broken, broken, provider="test"))
    executor.after.connect(ExecutionPlug(identity, broken))
    request = submit(executor, ctx, [call("one"), call("two")])
    with pytest.raises(RuntimeError, match="观察扩展失败"):
        asyncio.run(executor.execute(request))
    result = state(executor, ctx, request)
    assert result["status"] == "failed" and len(calls) == 1
    assert result["results"] == [{"call_id": "one", "name": "add", "status": "completed", "value": 5}]


def test_duplicate_names_and_mismatched_components_are_rejected(runtime):
    _, _, _ = runtime
    executor, _, _, _ = assemble(runtime)
    plug = executor.slot.links()[0].plug
    with pytest.raises(ValueError, match="名称重复"):
        executor.connect(TOOL, plug)
    with pytest.raises(ValueError, match="匹配组件"):
        executor.connect(TOOL, ExecutionPlug(Id("dev.tools:handlers/other"), plug.execute, plug.states))


def test_schema_uses_local_references_and_never_downloads_unknown_refs():
    spec = ToolSpec(
        COMPONENT,
        {
            **DEFINITION,
            "parameters": {
                "type": "object",
                "$defs": {"count": {"type": "integer", "minimum": 1}},
                "properties": {"n": {"$ref": "#/$defs/count"}},
                "required": ["n"],
            },
        },
    )
    spec.validate({"n": 2})
    external = ToolSpec(
        COMPONENT, {**DEFINITION, "parameters": {"type": "object", "$ref": "https://unavailable.invalid/schema"}}
    )
    with pytest.raises(Exception, match="Unresolvable"):
        external.validate({})


@pytest.mark.parametrize("failure_at", ["begin", "start", "finish", None])
def test_recorder_failure_stops_side_effects_and_preserves_original_results(runtime, failure_at):
    _, ctx, _ = runtime
    executor, calls, _, _ = assemble(runtime)
    events = []

    class Recorder:
        def record(self, name, value):
            events.append(name)
            if name == failure_at:
                raise OSError("证据写入失败")
            value.clear()

        def begin(self, request, batch):
            self.record("begin", batch)

        def start(self, request, call):
            self.record("start", call)

        def finish(self, request, result):
            self.record("finish", result)

    executor.recorder = Recorder()
    request = submit(executor, ctx, [call("one"), call("two")])
    if failure_at:
        with pytest.raises(RuntimeError if failure_at == "start" else OSError):
            asyncio.run(executor.execute(request))
        assert len(calls) == (1 if failure_at == "finish" else 0)
    else:
        asyncio.run(executor.execute(request))
        assert len(calls) == 2
        assert [item["value"] for item in state(executor, ctx, request)["results"]] == [5, 5]
        assert events == ["begin", "start", "finish", "start", "finish"]
    assert not executor._active


def test_recorder_captures_cancellation_and_reserves_unexecuted_calls(runtime):
    async def scenario():
        _, ctx, _ = runtime
        executor, calls, cleanups, entered = assemble(runtime, behavior="wait")
        events = []

        class Recorder:
            def begin(self, request, batch):
                events.append(("begin", [item["id"] for item in batch["calls"]]))

            def start(self, request, call):
                events.append(("start", call["id"]))

            def finish(self, request, result):
                events.append(("finish", result["status"]))

        executor.recorder = Recorder()
        request = submit(executor, ctx, [call("one"), call("two")])
        task = asyncio.create_task(executor.execute(request))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events == [("begin", ["one", "two"]), ("start", "one"), ("finish", "cancelled")]
        assert len(calls) == 1 and cleanups == ["one"]

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [TimeoutError(), ToolRejected("记录器拒绝")])
def test_recorder_start_errors_are_not_tool_timeout_or_rejection(runtime, error):
    _, ctx, _ = runtime
    executor, calls, _, _ = assemble(runtime)

    class Recorder:
        def begin(self, request, batch):
            pass

        def start(self, request, call):
            raise error

        def finish(self, request, result):
            raise AssertionError("记录器失败不得转成工具结果")

    executor.recorder = Recorder()
    request = submit(executor, ctx, [call("one"), call("two")])
    with pytest.raises(RuntimeError, match="记录失败") as failure:
        asyncio.run(executor.execute(request))
    assert failure.value.__cause__ is error and calls == []
    assert state(executor, ctx, request)["results"] == []
