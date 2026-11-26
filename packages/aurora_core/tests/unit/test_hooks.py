"""验证插槽兼容判断、实例绑定与连接调用。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.hooks import HookConnections, HookSlot
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

SLOT = Id("dev.example:slots/input")
HANDLER = Id("dev.example:handlers/process")


def setup_connections(slot=None, handler=None, interface=None):
    registry = bootstrap()
    registry.register(RegistryEntry(SLOT, "hook_slot", slot or HookSlot(), "example", interface="插槽描述"))
    registry.register(
        RegistryEntry(
            HANDLER, "hook_handler", handler or (lambda value: value), "example", slot=SLOT, interface=interface
        )
    )
    return registry, HookConnections(registry)


def connect(hooks, **kwargs):
    return hooks.connect(SLOT, HANDLER, slot_instance="root", handler_instance="first", **kwargs)


def test_slot_can_accept_different_description_without_schema():
    def accept(entry):
        return None if entry.interface == "双方约定" else "接口不兼容"

    _, hooks = setup_connections(HookSlot(accept), interface="双方约定")
    connection = connect(hooks)
    assert asyncio.run(hooks.invoke(connection, 3)) == 3
    _, rejected = setup_connections(HookSlot(accept))
    with pytest.raises(ValueError, match="接口不兼容"):
        connect(rejected)
    assert rejected.for_slot(SLOT, "root") == ()


def test_definitions_can_connect_multiple_bound_instances():
    class Handler:
        def __init__(self, multiplier):
            self.multiplier = multiplier

        def run(self, value):
            return self.multiplier * value

    _, hooks = setup_connections(handler=Handler.run)
    first = connect(hooks, target=Handler(2).run)
    second = hooks.connect(SLOT, HANDLER, slot_instance="other", handler_instance="second", target=Handler(3).run)
    assert asyncio.run(hooks.invoke(first, 4)) == 8
    assert asyncio.run(hooks.invoke(second, 4)) == 12
    assert hooks.for_slot(SLOT, "root") == (first,)
    assert hooks.for_slot(SLOT, "other") == (second,)


def test_priority_and_explicit_connection_order():
    _, hooks = setup_connections()
    first = connect(hooks, priority=10)
    earlier = hooks.connect(SLOT, HANDLER, slot_instance="root", handler_instance="earlier", priority=-1)
    tied = hooks.connect(SLOT, HANDLER, slot_instance="root", handler_instance="tied", priority=10)
    assert hooks.for_slot(SLOT, "root") == (earlier, first, tied)
    with pytest.raises(ValueError, match="重复"):
        connect(hooks)


def test_replacement_does_not_rewire_connected_implementation():
    registry, hooks = setup_connections(handler=lambda: 1)
    connection = connect(hooks)
    registry.replace(RegistryEntry(HANDLER, "hook_handler", lambda: 2, "replacement", slot=SLOT))
    assert asyncio.run(hooks.invoke(connection)) == 1
    assert hooks.disconnect(connection) is True
    assert hooks.disconnect(connection) is False
    replacement = connect(hooks)
    assert asyncio.run(hooks.invoke(replacement)) == 2
    with pytest.raises(ValueError, match="断开"):
        asyncio.run(hooks.invoke(connection))


def test_missing_wrong_kind_and_mismatched_slot_do_not_connect():
    registry, hooks = setup_connections()
    with pytest.raises(KeyError):
        hooks.connect(Id("dev.missing:slots/input"), HANDLER, slot_instance="root", handler_instance="first")
    registry.replace(RegistryEntry(HANDLER, "resource", lambda: None, "example"))
    with pytest.raises(TypeError, match="hook_handler"):
        connect(hooks)
    registry.replace(RegistryEntry(HANDLER, "hook_handler", lambda: None, "example", slot=Id("dev.other:slots/input")))
    with pytest.raises(ValueError, match="不符"):
        connect(hooks)
    assert hooks.for_slot(SLOT, "root") == ()


def test_foreign_handle_and_closed_manager_cannot_invoke():
    _, hooks = setup_connections()
    connection = connect(hooks)
    _, other = setup_connections()
    with pytest.raises(ValueError, match="不存在"):
        asyncio.run(other.invoke(connection, 1))
    hooks.close()
    hooks.close()
    with pytest.raises(RuntimeError, match="关闭"):
        asyncio.run(hooks.invoke(connection, 1))


def test_failure_contains_instance_context():
    def fail():
        raise ValueError("处理失败")

    _, hooks = setup_connections(handler=fail)
    connection = connect(hooks)
    with pytest.raises(ValueError, match="处理失败") as caught:
        asyncio.run(hooks.invoke(connection))
    assert any("first" in note and str(SLOT) in note for note in caught.value.__notes__)


def test_disconnect_does_not_cancel_in_flight_work():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def handler():
            entered.set()
            await release.wait()
            return "完成"

        _, hooks = setup_connections(handler=handler)
        connection = connect(hooks)
        task = asyncio.create_task(hooks.invoke(connection))
        await asyncio.wait_for(entered.wait(), timeout=1)
        hooks.disconnect(connection)
        with pytest.raises(ValueError, match="断开"):
            await hooks.invoke(connection)
        release.set()
        assert await task == "完成"

    asyncio.run(scenario())


def test_async_timeout_reaches_handler_cleanup():
    async def scenario():
        cleaned = asyncio.Event()

        async def handler():
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        _, hooks = setup_connections(handler=handler)
        connection = connect(hooks)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await hooks.invoke(connection)
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_cross_thread_connection_is_rejected():
    _, hooks = setup_connections()
    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(RuntimeError, match="宿主线程"):
        pool.submit(connect, hooks).result()
