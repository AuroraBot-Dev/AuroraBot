"""通过真实 core 宿主装配控制插件，验证组合执行和取消后的最终落盘。"""

import asyncio

import pytest
from aurora_control import (
    CONTROL_STATE,
    Branch,
    ExecutionPlug,
    ExecutionRequest,
    ExecutionSlot,
    Parallel,
    Serial,
    StateBinding,
    While,
    component_entries,
    plugin,
)
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import Lifecycle, LifecycleComponent, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService

DATA = Id("dev.control:state/value")


def make_plug(registry, name, execute, states=None, schema=None):
    definition = Id(f"dev.control_test:handlers/{name}")
    registry.register_many(component_entries(definition, execute, execute, provider="control_test"))
    return ExecutionPlug(definition, execute, states or {}, schema, instance_id=name)


def environment(root):
    registry = bootstrap()
    register_plugins(registry, (plugin(),))
    registry.register(RegistryEntry(DATA, "state_key", StateKey(), "example"))
    install_lifecycle_slots(registry)
    ctx = Context(registry)
    hooks = HookConnections(registry)
    storage = StorageService(root)
    store = storage.snapshot_store()
    lifecycle = Lifecycle(
        ctx,
        hooks,
        [LifecycleComponent("root")],
        persistence=ContextPersistence(ctx, store),
        storage=storage,
        timeout=0.05,
    )
    return ctx, hooks, lifecycle, registry


def test_composed_control_flow_restores_business_results_without_control_history(tmp_path):
    async def scenario():
        ctx, hooks, host, registry = environment(tmp_path)
        count = StateBinding(DATA, (("instance_id", "count"),))
        result = StateBinding(DATA, (("instance_id", "result"),))

        async def increment(request):
            value = count.get(ctx, request)
            assert isinstance(value, int)
            count.set(ctx, request, value + 1)

        async def left(request):
            StateBinding(DATA, (("instance_id", "left"),)).set(ctx, request, "left")

        async def right(request):
            await asyncio.sleep(0)
            StateBinding(DATA, (("instance_id", "right"),)).set(ctx, request, "right")

        parallel_slot = ExecutionSlot(Parallel.definition_id, hooks, instance_id="parallel")
        parallel_slot.connect(make_plug(registry, "left", left))
        parallel_slot.connect(make_plug(registry, "right", right))
        parallel = Parallel(ctx, parallel_slot, concurrency=2)

        branch_slot = ExecutionSlot(Branch.definition_id, hooks, instance_id="branch")
        branch_slot.connect(parallel.plug)
        branch = Branch(ctx, branch_slot, lambda request: "parallel" if count.get(ctx, request) == 2 else None)

        body_slot = ExecutionSlot(Serial.definition_id, hooks, instance_id="body")
        body_slot.connect(make_plug(registry, "count", increment, {"count": count}))
        body_slot.connect(branch.plug)
        body = Serial(ctx, body_slot)

        loop_slot = ExecutionSlot(While.definition_id, hooks, instance_id="loop")
        loop_slot.connect(body.plug)
        loop = While(ctx, loop_slot, lambda request: count.get(ctx, request) != 2, max_iterations=2)

        async def finish(request):
            values = [StateBinding(DATA, (("instance_id", name),)).get(ctx, request) for name in ("left", "right")]
            result.set(ctx, request, values)

        root_slot = ExecutionSlot(Serial.definition_id, hooks, instance_id="root")
        root_slot.connect(loop.plug)
        root_slot.connect(make_plug(registry, "result", finish, {"result": result}))
        request = ExecutionRequest("composed")
        await host.start(configure=lambda: count.set(ctx, request, 0))
        await host.run(Serial(ctx, root_slot).execute, request)
        assert result.get(ctx, request) == ["left", "right"]
        assert ctx.list(key=CONTROL_STATE) == ()
        await host.stop()

        restored, _, restarted, _ = environment(tmp_path)
        await restarted.start()
        assert result.get(restored, request) == ["left", "right"]
        assert restored.list(key=CONTROL_STATE) == ()
        await restarted.stop()

    asyncio.run(scenario())


def test_host_stop_cancels_parallel_work_and_persists_last_writes(tmp_path):
    async def scenario():
        ctx, hooks, host, registry = environment(tmp_path)
        entered = asyncio.Event()
        active = 0

        def worker(name):
            async def execute(request):
                nonlocal active
                active += 1
                if active == 2:
                    entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(0)
                    StateBinding(DATA, (("instance_id", name),)).set(ctx, request, "cleaned")
                    active -= 1

            return make_plug(registry, name, execute)

        slot = ExecutionSlot(Parallel.definition_id, hooks, instance_id="root")
        slot.connect(worker("first"))
        slot.connect(worker("second"))
        request = ExecutionRequest("cancelled")
        await host.start()
        task = asyncio.create_task(host.run(Parallel(ctx, slot, concurrency=2).execute, request))
        await asyncio.wait_for(entered.wait(), 1)
        await host.stop()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert active == 0

        restored, _, restarted, _ = environment(tmp_path)
        await restarted.start()
        for name in ("first", "second"):
            assert StateBinding(DATA, (("instance_id", name),)).get(restored, request) == "cleaned"
        assert restored.list(key=CONTROL_STATE) == ()
        await restarted.stop()

    asyncio.run(scenario())
