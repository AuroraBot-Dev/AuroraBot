"""验证 ReAct 的重复激活、引导消费边界、具名阶段连接与失败收尾。"""

import asyncio

import pytest
from aurora_agent.react import PHASE_IDS, AgentBusyError, ReActAgent, plugin
from aurora_control import (
    ExecutionPlug,
    ExecutionRequest,
    InstanceStateBinding,
    LoopLimitExceeded,
    StateBinding,
    component_entries,
)
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

STATE = Id("dev.react:state/data")


@pytest.fixture
def runtime():
    registry = bootstrap()
    register_plugins(registry, (plugin(),))
    registry.register(RegistryEntry(STATE, "state_key", StateKey(), "test"))
    ctx = Context(registry)
    hooks = HookConnections(registry)
    yield registry, ctx, hooks
    hooks.close()
    ctx.close()


def assemble(runtime, *, instance_id="bot", max_iterations=None):
    registry, ctx, hooks = runtime

    def binding(name):
        return StateBinding(STATE, (("instance_id", instance_id), ("name", name)))

    def fixed(name):
        return InstanceStateBinding(STATE, (("instance_id", instance_id), ("name", name)))

    agent = ReActAgent(
        ctx,
        hooks,
        instance_id=instance_id,
        inbox=fixed("inbox"),
        progress=fixed("progress"),
        runtime=fixed("runtime"),
        batch=binding("batch"),
        decision=binding("decision"),
        max_iterations=max_iterations,
    )
    seen = []
    calls = []

    def connect(phase, handler):
        definition = Id(f"dev.react:handlers/{instance_id}/{phase}")
        registry.register_many(component_entries(definition, handler, handler, provider="test"))
        return agent.slots[phase].connect(ExecutionPlug(definition, handler, instance_id=f"{instance_id}-{phase}"))

    async def prepare(request):
        batch = agent.batch.get(ctx, request)
        assert isinstance(batch, list)
        seen.extend(batch)
        calls.append(("prepare", request))

    async def infer(request):
        calls.append(("infer", request))
        agent.decision.set(ctx, request, "finish")

    connect("prepare", prepare)
    connect("infer", infer)

    def replace(phase, handler):
        for link in agent.slots[phase].links():
            hooks.disconnect(link.connection)
        definition = Id(f"dev.react:handlers/{instance_id}/{phase}/replacement")
        registry.register_many(component_entries(definition, handler, handler, provider="test"))
        agent.slots[phase].connect(ExecutionPlug(definition, handler))

    return agent, seen, calls, connect, replace


def guidance(sequence):
    return {"sequence": sequence, "id": f"event-{sequence}", "payload": {"content": f"引导 {sequence}"}}


def test_unbounded_run_accepts_guidance_and_cancellation_after_many_iterations(runtime):
    async def scenario():
        _, ctx, _ = runtime
        agent, seen, _, _, replace = assemble(runtime)
        request = ExecutionRequest("continuous")
        reached = asyncio.Event()

        async def infer(current):
            iteration = record(agent, ctx, current)["iterations"]
            if iteration == 20:
                agent.inbox.set(ctx, request, [guidance(1)])
            if iteration >= 25:
                reached.set()
            agent.decision.set(ctx, current, "continue")

        replace("infer", infer)
        task = asyncio.create_task(agent.execute(request))
        await asyncio.wait_for(reached.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert seen == [guidance(1)]
        assert record(agent, ctx, request)["status"] == "cancelled"
        assert record(agent, ctx, request)["iterations"] >= 25

    asyncio.run(scenario())


def record(agent, ctx, request):
    value = agent.runtime.get(ctx, request)
    assert isinstance(value, dict)
    return value


def test_repeat_activation_retains_progress_and_uses_independent_execution_ids(runtime):
    registry, ctx, _ = runtime
    agent, seen, calls, _, _ = assemble(runtime)
    first, second = ExecutionRequest("first"), ExecutionRequest("second")
    agent.inbox.set(ctx, first, [guidance(1)])
    asyncio.run(agent.execute(first))
    agent.inbox.set(ctx, second, [guidance(1), guidance(2)])
    asyncio.run(agent.plug(second))
    assert seen == [guidance(1), guidance(2)]
    assert agent.progress.get(ctx, first) == agent.progress.get(ctx, second) == 2
    assert record(agent, ctx, second)["status"] == "completed"
    assert record(agent, ctx, second)["run_id"] == "second"
    assert {request.run_id for _, request in calls} == {"first", "second"}
    assert len({request.execution_id for _, request in calls}) == 4
    assert all(request.parent_execution_id == first.execution_id for _, request in calls[:2])
    assert registry.get(agent.definition_id).kind == "component"
    assert registry.get(agent.plug.execute_id).interface == agent.definition_id
    for phase, slot_id in PHASE_IDS.items():
        assert registry.get(slot_id).kind == "hook_slot"
        assert agent.slots[phase].slot_id == slot_id
        assert agent.slots[phase].instance_id == agent.instance_id
    assert agent.plug.states["inbox"] == agent.inbox
    assert len(ctx.list()) == 3  # 仅保留 inbox、消费进度与最近运行状态。


def test_empty_activation_can_finish_without_action_or_output(runtime):
    _, ctx, _ = runtime
    agent, seen, calls, _, _ = assemble(runtime)
    request = ExecutionRequest("idle")
    asyncio.run(agent.execute(request))
    assert seen == [] and [phase for phase, _ in calls] == ["prepare", "infer"]
    assert record(agent, ctx, request)["status"] == "completed"
    assert len(ctx.list()) == 1


def test_requested_finish_settles_observation_and_preserves_new_guidance(runtime):
    _, ctx, _ = runtime
    agent, seen, _, connect, replace = assemble(runtime, max_iterations=1)
    request = ExecutionRequest("self-finish")
    phases = []
    assert not agent.request_finish(request.run_id)

    async def infer(child):
        agent.decision.set(ctx, child, "act")

    async def act(child):
        assert not agent.request_finish("another-run")
        assert agent.request_finish(child.run_id)
        agent.inbox.set(ctx, child, [guidance(1), guidance(2)])
        phases.append("act")

    async def observe(child):
        assert agent.finish_requested
        phases.append("observe")

    async def finish(child):
        assert not agent.request_finish(child.run_id)
        phases.append("finish")

    replace("infer", infer)
    connect("act", act)
    connect("observe", observe)
    connect("finish", finish)
    agent.inbox.set(ctx, request, [guidance(1)])
    asyncio.run(agent.execute(request))
    assert phases == ["act", "observe", "finish"]
    assert seen == [guidance(1)] and agent.pending(request) == [guidance(2)]
    assert record(agent, ctx, request)["status"] == "completed"
    assert not agent.finish_requested and not agent.request_finish(request.run_id)


@pytest.mark.parametrize("during", ["prepare", "infer"])
def test_guidance_during_execution_is_consumed_in_current_run(runtime, during):
    _, ctx, _ = runtime
    agent, seen, _, _, replace = assemble(runtime)
    request = ExecutionRequest("same-run")

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        invocations = []

        async def handler(child):
            invocations.append(child)
            if len(invocations) == 1:
                entered.set()
                await release.wait()
            if during == "prepare":
                batch = agent.batch.get(ctx, child)
                assert isinstance(batch, list)
                seen.extend(batch)
            else:
                agent.decision.set(ctx, child, "finish")

        replace(during, handler)
        agent.inbox.set(ctx, request, [guidance(1)])
        task = asyncio.create_task(agent.execute(request))
        await entered.wait()
        agent.inbox.set(ctx, request, [guidance(1), guidance(2)])
        release.set()
        await task
        assert seen == [guidance(1), guidance(2)]
        assert len(invocations) == 2
        assert {child.run_id for child in invocations} == {request.run_id}
        assert agent.progress.get(ctx, request) == 2

    asyncio.run(scenario())


def test_finish_boundary_input_remains_available_for_next_activation(runtime):
    _, ctx, _ = runtime
    agent, seen, _, connect, _ = assemble(runtime)
    first = ExecutionRequest("first")

    async def finish(request):
        if request.run_id == "first":
            agent.inbox.set(ctx, request, [guidance(1)])

    connect("finish", finish)
    asyncio.run(agent.execute(first))
    assert seen == [] and agent.pending(first) == [guidance(1)]
    asyncio.run(agent.execute(ExecutionRequest("second")))
    assert seen == [guidance(1)] and agent.pending(first) == []


def test_busy_call_is_rejected_without_disturbing_active_run(runtime):
    _, ctx, _ = runtime
    agent, _, _, _, replace = assemble(runtime)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def infer(request):
            entered.set()
            await release.wait()
            agent.decision.set(ctx, request, "finish")

        replace("infer", infer)
        first = ExecutionRequest("first")
        task = asyncio.create_task(agent.execute(first))
        await entered.wait()
        before = ctx.snapshot()
        with pytest.raises(AgentBusyError):
            await agent.execute(ExecutionRequest("second"))
        assert ctx.snapshot() == before
        release.set()
        await task
        assert record(agent, ctx, first)["run_id"] == "first"

    asyncio.run(scenario())


def test_cancel_waits_for_tool_cleanup_and_allows_later_activation(runtime):
    _, ctx, _ = runtime
    agent, _, _, connect, replace = assemble(runtime)

    async def scenario():
        entered = asyncio.Event()
        cleaned = []

        async def infer(request):
            agent.decision.set(ctx, request, "act" if request.run_id == "cancel" else "finish")

        async def act(request):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleaned.append(request.run_id)

        async def observe(request):
            pytest.fail("取消的动作不进入 observe")

        replace("infer", infer)
        connect("act", act)
        connect("observe", observe)
        request = ExecutionRequest("cancel")
        task = asyncio.create_task(agent.execute(request))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned == ["cancel"]
        assert record(agent, ctx, request)["status"] == "cancelled"
        assert len(ctx.list()) == 1
        await agent.execute(ExecutionRequest("retry"))
        assert record(agent, ctx, request)["status"] == "completed"

    asyncio.run(scenario())


def test_prepare_failure_does_not_acknowledge_guidance_and_preserves_both_errors(runtime):
    _, ctx, _ = runtime
    agent, _, _, connect, replace = assemble(runtime)
    request = ExecutionRequest("failure")
    agent.inbox.set(ctx, request, [guidance(1)])
    statuses = []
    ctx.subscribe(
        lambda change: statuses.append(change.value["status"]), key=STATE, location=dict(agent.runtime.location)
    )

    async def prepare(request):
        raise ValueError("准备失败")

    async def error(request):
        raise RuntimeError("错误处理失败")

    replace("prepare", prepare)
    connect("error", error)
    with pytest.raises(ExceptionGroup) as caught:
        asyncio.run(agent.execute(request))
    assert [type(error) for error in caught.value.exceptions] == [ValueError, RuntimeError]
    assert agent.pending(request) == [guidance(1)]
    assert record(agent, ctx, request)["status"] == "failed"
    assert statuses.count("failed") == 1
    assert "completed" not in statuses and "cancelled" not in statuses


@pytest.mark.parametrize("decision", ["continue", "act", "unknown", None])
def test_loop_limit_and_missing_actions_fail_explicitly(runtime, decision):
    _, ctx, _ = runtime
    agent, _, _, _, replace = assemble(runtime, max_iterations=2)
    request = ExecutionRequest("limit")

    async def infer(child):
        if decision is not None:
            agent.decision.set(ctx, child, decision)

    replace("infer", infer)
    with pytest.raises(LoopLimitExceeded if decision == "continue" else ValueError):
        asyncio.run(agent.execute(request))
    assert record(agent, ctx, request)["status"] == "failed"


def test_instances_do_not_share_guidance_or_progress(runtime):
    _, ctx, _ = runtime
    first, first_seen, _, _, _ = assemble(runtime, instance_id="one")
    second, second_seen, _, _, _ = assemble(runtime, instance_id="two")
    request = ExecutionRequest("shared-run")
    first.inbox.set(ctx, request, [guidance(1)])

    async def scenario():
        await asyncio.gather(first.execute(request), second.execute(request))

    asyncio.run(scenario())
    assert first_seen == [guidance(1)] and second_seen == []
    assert record(first, ctx, request)["status"] == record(second, ctx, request)["status"] == "completed"


@pytest.mark.parametrize(
    "value",
    [{}, [{}], [guidance(2), guidance(1)], [guidance(1), guidance(1)], [{**guidance(1), "sequence": True}]],
)
def test_invalid_inbox_is_rejected_before_prepare(runtime, value):
    _, ctx, _ = runtime
    agent, seen, calls, _, _ = assemble(runtime)
    request = ExecutionRequest("invalid")
    agent.inbox.set(ctx, request, value)
    with pytest.raises((ValueError, TypeError)):
        asyncio.run(agent.execute(request))
    assert seen == [] and calls == []
