"""验证显式依赖顺序、部分启动清理和在途工作收尾。"""

import asyncio

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import (
    CLEAN,
    CONFIG,
    PREPARE,
    START,
    STOP,
    Lifecycle,
    LifecycleComponent,
    install_lifecycle_slots,
)
from aurora_core.registry import RegistryEntry


def environment(components, *, timeout: float = 1):
    registry = bootstrap()
    install_lifecycle_slots(registry)
    ctx = Context(registry)
    hooks = HookConnections(registry)
    lifecycle = Lifecycle(ctx, hooks, components, timeout=timeout)
    return registry, ctx, hooks, lifecycle


def handler(registry, hooks, phase, instance, callback, *, name="handler"):
    identity = Id(f"dev.lifecycle:handlers/{instance}/{phase.local_path}/{name}")
    registry.register(RegistryEntry(identity, "hook_handler", callback, "测试插件", slot=phase))
    return hooks.connect(phase, identity, slot_instance=instance, handler_instance=instance)


def test_dependencies_prepare_start_and_stop_in_order():
    async def scenario():
        calls = []
        components = [
            LifecycleComponent("app", ("service",), lambda: calls.append("quiesce:app")),
            LifecycleComponent("service", stop_accepting=lambda: calls.append("quiesce:service")),
        ]
        registry, _, hooks, lifecycle = environment(components)
        for phase in (CONFIG, PREPARE, START, STOP, CLEAN):
            for instance in ("app", "service"):
                handler(
                    registry,
                    hooks,
                    phase,
                    instance,
                    lambda phase=phase, instance=instance: calls.append(f"{phase.local_path}:{instance}"),
                )
        await lifecycle.start()
        await lifecycle.stop()
        await lifecycle.stop()
        assert calls == [
            "config:service",
            "config:app",
            "prepare:service",
            "prepare:app",
            "start:service",
            "start:app",
            "quiesce:app",
            "quiesce:service",
            "stop:app",
            "stop:service",
            "clean:app",
            "clean:service",
        ]
        assert lifecycle.state == "stopped"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "components",
    [
        [LifecycleComponent("a", ("missing",))],
        [LifecycleComponent("a", ("b",)), LifecycleComponent("b", ("a",))],
        [LifecycleComponent("a"), LifecycleComponent("a")],
    ],
)
def test_invalid_dependencies_fail_before_execution(components):
    with pytest.raises(ValueError):
        environment(components)


def test_failed_prepare_stops_partially_prepared_component_and_its_dependency():
    async def scenario():
        calls = []
        registry, ctx, hooks, lifecycle = environment(
            [LifecycleComponent("service"), LifecycleComponent("broken", ("service",)), LifecycleComponent("unused")]
        )

        def fail():
            calls.append("partial:broken")
            raise ValueError("prepare 失败")

        handler(registry, hooks, PREPARE, "broken", fail)
        for instance in ("service", "broken", "unused"):
            handler(registry, hooks, STOP, instance, lambda instance=instance: calls.append(f"stop:{instance}"))
        with pytest.raises(ValueError, match="prepare 失败"):
            await lifecycle.start()
        assert calls == ["partial:broken", "stop:broken", "stop:service"]
        assert lifecycle.state == "stopped"
        with pytest.raises(RuntimeError, match="关闭"):
            ctx.list()

    asyncio.run(scenario())


def test_failed_stop_keeps_dependencies_and_retry_skips_successful_handlers():
    async def scenario():
        calls = []
        fail = True
        registry, ctx, hooks, lifecycle = environment(
            [LifecycleComponent("service"), LifecycleComponent("app", ("service",))]
        )

        def stop():
            if fail:
                raise ValueError("stop 失败")
            calls.append("stop:app")

        handler(registry, hooks, STOP, "app", lambda: calls.append("first"), name="first")
        handler(registry, hooks, STOP, "app", stop, name="last")
        handler(registry, hooks, STOP, "service", lambda: calls.append("stop:service"))
        await lifecycle.start()
        with pytest.raises(ValueError, match="stop 失败"):
            await lifecycle.stop()
        assert lifecycle.state == "failed"
        assert ctx.list() == ()
        assert calls == ["first"]
        fail = False
        await lifecycle.stop()
        assert calls == ["first", "stop:app", "stop:service"]

    asyncio.run(scenario())


def test_stop_rejects_new_work_and_waits_before_component_stop():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        gate_closed = asyncio.Event()
        calls = []
        registry, _, hooks, lifecycle = environment([LifecycleComponent("app", stop_accepting=gate_closed.set)])
        handler(registry, hooks, STOP, "app", lambda: calls.append("stop"))

        async def work():
            entered.set()
            await release.wait()
            calls.append("work")

        await lifecycle.start()
        task = asyncio.create_task(lifecycle.run(work))
        await entered.wait()
        stop = asyncio.create_task(lifecycle.stop())
        await gate_closed.wait()
        with pytest.raises(RuntimeError, match="新工作"):
            await lifecycle.run(lambda: None)
        assert calls == []
        release.set()
        await task
        await stop
        assert calls == ["work", "stop"]

    asyncio.run(scenario())


def test_drain_timeout_requests_cancellation_and_waits_for_cleanup():
    async def scenario():
        entered = asyncio.Event()
        cleaned = asyncio.Event()
        _, _, _, lifecycle = environment([], timeout=0.01)

        async def work():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        await lifecycle.start()
        task = asyncio.create_task(lifecycle.run(work))
        await entered.wait()
        await lifecycle.stop()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_cancelled_stop_waiter_does_not_interrupt_cleanup():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        registry, _, hooks, lifecycle = environment([LifecycleComponent("app")])

        async def stop():
            entered.set()
            await release.wait()

        handler(registry, hooks, STOP, "app", stop)
        await lifecycle.start()
        waiter = asyncio.create_task(lifecycle.stop())
        await entered.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        await lifecycle.stop()
        assert lifecycle.state == "stopped"

    asyncio.run(scenario())


def test_cancelled_start_cleans_attempted_component():
    async def scenario():
        entered = asyncio.Event()
        stopped = asyncio.Event()
        registry, _, hooks, lifecycle = environment([LifecycleComponent("app")])

        async def prepare():
            entered.set()
            await asyncio.Event().wait()

        handler(registry, hooks, PREPARE, "app", prepare)
        handler(registry, hooks, STOP, "app", stopped.set)
        task = asyncio.create_task(lifecycle.start())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()
        assert lifecycle.state == "stopped"

    asyncio.run(scenario())


def test_work_that_delays_cancellation_keeps_resources_until_retry():
    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        registry, ctx, hooks, lifecycle = environment([LifecycleComponent("app")], timeout=0.01)
        stopped = []
        handler(registry, hooks, STOP, "app", lambda: stopped.append(True))

        async def work():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()

        await lifecycle.start()
        task = asyncio.create_task(lifecycle.run(work))
        await entered.wait()
        with pytest.raises(TimeoutError, match="未完成取消"):
            await lifecycle.stop()
        assert stopped == []
        assert ctx.list() == ()
        release.set()
        await task
        await lifecycle.stop()
        assert stopped == [True]

    asyncio.run(scenario())


def test_start_and_cleanup_errors_are_both_reported():
    async def scenario():
        registry, ctx, hooks, lifecycle = environment([LifecycleComponent("app")])

        def start():
            raise ValueError("启动失败")

        def stop():
            raise OSError("收尾失败")

        handler(registry, hooks, START, "app", start)
        connection = handler(registry, hooks, STOP, "app", stop)
        with pytest.raises(ExceptionGroup) as caught:
            await lifecycle.start()
        assert [type(error) for error in caught.value.exceptions] == [ValueError, OSError]
        assert ctx.list() == ()
        hooks.disconnect(connection)
        await lifecycle.stop()

    asyncio.run(scenario())


def test_stop_handler_timeout_preserves_dependencies_for_retry():
    async def scenario():
        registry, ctx, hooks, lifecycle = environment(
            [LifecycleComponent("service"), LifecycleComponent("app", ("service",))], timeout=0.01
        )
        cleaned = asyncio.Event()
        ready = asyncio.Event()
        stopped = []

        async def stop():
            try:
                await ready.wait()
            finally:
                cleaned.set()

        handler(registry, hooks, STOP, "app", stop)
        handler(registry, hooks, STOP, "service", lambda: stopped.append(True))
        await lifecycle.start()
        with pytest.raises(TimeoutError):
            await lifecycle.stop()
        assert cleaned.is_set()
        assert stopped == []
        assert ctx.list() == ()
        ready.set()
        await lifecycle.stop()
        assert stopped == [True]

    asyncio.run(scenario())


def test_configuration_failure_does_not_prepare_components():
    async def scenario():
        registry, ctx, hooks, lifecycle = environment([LifecycleComponent("app")])
        calls = []
        handler(registry, hooks, PREPARE, "app", lambda: calls.append("prepare"))

        def configure():
            raise ValueError("配置不合法")

        with pytest.raises(ValueError, match="配置不合法"):
            await lifecycle.start(configure=configure)
        assert calls == []
        assert lifecycle.state == "stopped"
        with pytest.raises(RuntimeError, match="关闭"):
            ctx.list()

    asyncio.run(scenario())


def test_failed_config_cleans_only_entered_components_without_prepare_or_stop():
    async def scenario():
        registry, _, hooks, lifecycle = environment(
            [LifecycleComponent("a"), LifecycleComponent("b"), LifecycleComponent("c")]
        )
        calls = []

        def fail():
            raise ValueError("配置失败")

        handler(registry, hooks, CONFIG, "b", fail)
        for instance in ("a", "b", "c"):
            for phase in (PREPARE, STOP, CLEAN):
                handler(
                    registry,
                    hooks,
                    phase,
                    instance,
                    lambda phase=phase, instance=instance: calls.append((phase, instance)),
                )
        with pytest.raises(ValueError, match="配置失败"):
            await lifecycle.start()
        assert calls == [(CLEAN, "b"), (CLEAN, "a")]

    asyncio.run(scenario())


def test_clean_failure_retries_without_repeating_stop_or_successful_clean_handlers():
    async def scenario():
        registry, _, hooks, lifecycle = environment(
            [LifecycleComponent("service"), LifecycleComponent("app", ("service",))]
        )
        calls = []
        failing = True

        def clean():
            if failing:
                raise OSError("关闭失败")
            calls.append("clean:app:last")

        for instance in ("app", "service"):
            handler(registry, hooks, STOP, instance, lambda instance=instance: calls.append("stop:" + instance))
        handler(registry, hooks, CLEAN, "app", lambda: calls.append("clean:app:first"), name="first")
        handler(registry, hooks, CLEAN, "app", clean, name="last")
        handler(registry, hooks, CLEAN, "service", lambda: calls.append("clean:service"))
        await lifecycle.start()
        with pytest.raises(OSError):
            await lifecycle.stop()
        assert calls == ["stop:app", "stop:service", "clean:app:first"]
        failing = False
        await lifecycle.stop()
        assert calls == ["stop:app", "stop:service", "clean:app:first", "clean:app:last", "clean:service"]

    asyncio.run(scenario())
