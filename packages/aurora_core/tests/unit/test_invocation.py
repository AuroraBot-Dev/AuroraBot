"""验证单次操作调用的同步、异步、错误与取消语义。"""

import asyncio

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ids import Id
from aurora_core.invocation import invoke_operation
from aurora_core.registry import RegistryEntry

OPERATION = Id("dev.example:operations/run")


def test_business_keywords_do_not_collide_with_invocation_routing():
    registry = bootstrap()
    registry.register(RegistryEntry(OPERATION, "operation", lambda **values: values, "example"))
    values = {"target": "service", "registry": "business", "identity": "item"}
    assert asyncio.run(invoke_operation(registry, OPERATION, **values)) == values


def test_sync_and_async_results_and_keyword_arguments():
    registry = bootstrap()
    registry.register(RegistryEntry(OPERATION, "operation", lambda value, *, extra: value + extra, "example"))
    assert asyncio.run(invoke_operation(registry, OPERATION, 1, extra=2)) == 3

    async def execute(value):
        return value * 2

    registry.replace(RegistryEntry(OPERATION, "operation", execute, "example"))
    assert asyncio.run(invoke_operation(registry, OPERATION, 3)) == 6


@pytest.mark.parametrize("kind,target", [("resource", lambda: None), ("operation", object())])
def test_addressable_does_not_mean_callable_operation(kind, target):
    registry = bootstrap()
    registry.register(RegistryEntry(OPERATION, kind, target, "example"))
    with pytest.raises(TypeError, match="operation"):
        asyncio.run(invoke_operation(registry, OPERATION))


def test_missing_operation_reports_failure():
    with pytest.raises(KeyError):
        asyncio.run(invoke_operation(bootstrap(), OPERATION))


def test_exception_is_preserved():
    def execute():
        raise ValueError("业务错误")

    registry = bootstrap()
    registry.register(RegistryEntry(OPERATION, "operation", execute, "example"))
    with pytest.raises(ValueError, match="业务错误"):
        asyncio.run(invoke_operation(registry, OPERATION))


def test_async_cancellation_reaches_handler():
    async def scenario():
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def execute():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        registry = bootstrap()
        registry.register(RegistryEntry(OPERATION, "operation", execute, "example"))
        task = asyncio.create_task(invoke_operation(registry, OPERATION))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()

    asyncio.run(scenario())
