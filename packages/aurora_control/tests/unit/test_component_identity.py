"""验证组件定义、端口、实例和执行身份的独立寻址。"""

import asyncio
from uuid import UUID

import pytest
from aurora_agent.model import ModelCall
from aurora_agent.model import plugin as model_plugin
from aurora_control import (
    CONTROL_STATE,
    Branch,
    Controller,
    ExecutionPlug,
    ExecutionRequest,
    ExecutionSlot,
    Parallel,
    Serial,
    While,
    component_entries,
    plugin,
)
from aurora_core.admission import inspect_admissions
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id


@pytest.fixture
def runtime():
    registry = bootstrap()
    register_plugins(registry, (plugin(), model_plugin()))
    ctx = Context(registry)
    hooks = HookConnections(registry)
    yield registry, ctx, hooks
    hooks.close()
    ctx.close()


def test_component_catalog_preserves_definitions_ports_and_providers(runtime):
    registry, _, _ = runtime
    for component in (Controller, Serial, Branch, While, Parallel, ModelCall):
        definition = registry.get(component.definition_id)
        assert definition.kind == "component" and definition.target is component
        execute = registry.get(Id(f"{component.definition_id}/execute"))
        assert execute.kind == "hook_handler" and execute.interface == component.definition_id
        assert execute.target == component.execute and execute.provider == definition.provider
        if component is not ModelCall:
            assert registry.get(Id(f"{component.definition_id}/children")).kind == "hook_slot"
    assert all(item.status == "accepted" for item in inspect_admissions(registry))
    assert Branch.definition_id == Id("org.aurora.control:handlers/control/branch")


def test_auto_instances_share_definition_but_keep_targets_and_execution_ids(runtime):
    registry, ctx, hooks = runtime
    definition = Id("dev.identity:handlers/worker")
    calls = []

    class Worker:
        def __init__(self, label):
            self.label = label

        async def execute(self, request):
            calls.append((self.label, request))

    registry.register_many(component_entries(definition, Worker, Worker.execute, provider="third_party"))
    first = ExecutionPlug(definition, Worker("first").execute)
    second = ExecutionPlug(definition, Worker("second").execute)
    assert UUID(first.instance_id).version == UUID(second.instance_id).version == 4
    assert first.instance_id != second.instance_id
    assert first.reference == f"{definition}.{first.instance_id}"
    slot = ExecutionSlot(Serial.definition_id, hooks)
    other = ExecutionSlot(Serial.definition_id, hooks)
    assert UUID(slot.instance_id).version == 4 and slot.instance_id != other.instance_id
    root = Serial(ctx, slot)
    assert root.plug.reference == slot.reference == root.plug.reference
    links = [slot.connect(first), slot.connect(second)]
    assert links[0].connection.handler == links[1].connection.handler == first.execute_id
    assert links[0].connection.handler_instance != links[1].connection.handler_instance
    assert registry.get(first.execute_id).provider == "third_party"
    request = ExecutionRequest("run")
    asyncio.run(root.execute(request))
    assert [label for label, _ in calls] == ["first", "second"]
    assert len({execution.execution_id for _, execution in calls}) == 2
    assert all(execution.parent_execution_id == request.execution_id for _, execution in calls)


def test_nested_controllers_use_their_own_ports(runtime):
    _, ctx, hooks = runtime
    root = Serial(ctx, ExecutionSlot(Serial.definition_id, hooks))
    branch = Branch(ctx, ExecutionSlot(Branch.definition_id, hooks), lambda _: None)
    link = root.slot.connect(branch.plug)
    assert link.connection.slot == Id("org.aurora.control:handlers/control/serial/children")
    assert link.connection.handler == Id("org.aurora.control:handlers/control/branch/execute")
    asyncio.run(root.execute(ExecutionRequest("run")))
    assert ctx.list(key=CONTROL_STATE) == ()


def test_connections_reject_missing_or_mismatched_definitions(runtime):
    _, ctx, hooks = runtime
    slot = ExecutionSlot(Serial.definition_id, hooks)

    async def execute(request):
        pytest.fail("拒绝连接时不得执行")

    with pytest.raises(KeyError):
        slot.connect(ExecutionPlug(Id("dev.identity:handlers/missing"), execute))
    branch = Branch(ctx, ExecutionSlot(Branch.definition_id, hooks), lambda _: None)
    with pytest.raises(ValueError, match="组件定义不符"):
        hooks.connect(
            slot.children_id,
            Id(f"{Serial.definition_id}/execute"),
            slot_instance=slot.instance_id,
            handler_instance=branch.plug.instance_id,
            target=branch.plug,
        )
    with pytest.raises(ValueError, match="组件与插槽定义不符"):
        Serial(ctx, branch.slot)
    assert slot.links() == ()


def test_duplicate_child_names_are_rejected_even_with_distinct_definitions(runtime):
    _, ctx, hooks = runtime
    slot = ExecutionSlot(Branch.definition_id, hooks)
    first = Serial(ctx, ExecutionSlot(Serial.definition_id, hooks, instance_id="child"))
    second = Parallel(ctx, ExecutionSlot(Parallel.definition_id, hooks, instance_id="child"), concurrency=1)
    link = slot.connect(first.plug)
    with pytest.raises(ValueError, match="实例标识重复"):
        slot.connect(second.plug)
    hooks.disconnect(link.connection)
    assert slot.connect(second.plug).connection.handler == second.plug.execute_id


def test_control_state_separates_definitions_with_same_local_instance_and_execution(runtime):
    registry, ctx, hooks = runtime

    async def scenario():
        entered = {name: asyncio.Event() for name in ("serial", "parallel")}
        release = {name: asyncio.Event() for name in entered}
        tasks = []
        request = ExecutionRequest("run")
        for name, kind in (("serial", Serial), ("parallel", Parallel)):

            async def execute(request, name=name):
                entered[name].set()
                await release[name].wait()

            definition = Id(f"dev.identity:handlers/{name}")
            registry.register_many(component_entries(definition, execute, execute, provider="example"))
            slot = ExecutionSlot(kind.definition_id, hooks, instance_id="root")
            slot.connect(ExecutionPlug(definition, execute))
            controller = Serial(ctx, slot) if kind is Serial else Parallel(ctx, slot, concurrency=1)
            tasks.append(asyncio.create_task(controller.execute(request)))
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered.values())), 1)
        addresses = ctx.list(key=CONTROL_STATE)
        assert {dict(address.location)["definition_id"] for address in addresses} == {
            str(Serial.definition_id),
            str(Parallel.definition_id),
        }
        release["serial"].set()
        await tasks[0]
        assert len(ctx.list(key=CONTROL_STATE)) == 1
        release["parallel"].set()
        await tasks[1]
        assert ctx.list(key=CONTROL_STATE) == ()

    asyncio.run(scenario())
