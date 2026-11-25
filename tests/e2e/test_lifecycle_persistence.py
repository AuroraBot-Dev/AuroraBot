"""验证组件最终写入、宿主落盘与失败后的恢复边界。"""

import asyncio
from threading import Event

import pytest
from aurora_core import Id, entry_from, hook_handler
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import CLEAN, PREPARE, STOP, Lifecycle, LifecycleComponent, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.snapshots import JsonSnapshotStore
from aurora_core.storage import StorageService

VALUE = Id("dev.lifecycle:state/value")


def environment(root):
    registry = bootstrap()
    install_lifecycle_slots(registry)
    registry.register(RegistryEntry(VALUE, "state_key", StateKey(), "测试插件"))
    ctx = Context(registry)
    hooks = HookConnections(registry)
    storage = StorageService(root)
    store = storage.snapshot_store()
    persistence = ContextPersistence(ctx, store, interval=60)
    lifecycle = Lifecycle(ctx, hooks, [LifecycleComponent("app")], persistence=persistence, storage=storage)
    return registry, ctx, hooks, storage, store, lifecycle


@pytest.mark.parametrize("stop_handler", [True, False])
@pytest.mark.parametrize("phase", [STOP, CLEAN])
def test_final_snapshot_is_host_owned_and_restored_before_prepare(tmp_path, stop_handler, phase):
    async def scenario():
        registry, ctx, hooks, storage, _, lifecycle = environment(tmp_path)

        @hook_handler("dev.lifecycle:handlers/stop", slot=phase)
        def stop():
            storage.set("dev.lifecycle", "finished", True)
            ctx.set(VALUE, "stopped")

        registry.register(entry_from(stop, provider="测试插件"))
        connection = hooks.connect(
            phase, Id("dev.lifecycle:handlers/stop"), slot_instance="app", handler_instance="app"
        )
        if not stop_handler:
            hooks.disconnect(connection)
        await lifecycle.start()
        ctx.set(VALUE, "running")
        await lifecycle.stop()
        with pytest.raises(RuntimeError, match="关闭"):
            storage.keys("dev.lifecycle")
        with pytest.raises(RuntimeError, match="关闭"):
            ctx.list()

        registry, ctx, hooks, storage, _, lifecycle = environment(tmp_path)
        restored = []

        @hook_handler("dev.lifecycle:handlers/prepare", slot=PREPARE)
        def prepare():
            restored.append(ctx.get(VALUE))

        registry.register(entry_from(prepare, provider="测试插件"))
        hooks.connect(PREPARE, Id("dev.lifecycle:handlers/prepare"), slot_instance="app", handler_instance="app")
        await lifecycle.start()
        assert restored == ["stopped" if stop_handler else "running"]
        if stop_handler:
            assert storage.get("dev.lifecycle", "finished") is True
        await lifecycle.stop()

    asyncio.run(scenario())


def test_final_flush_failure_preserves_state_and_storage_for_retry(tmp_path, monkeypatch):
    async def scenario():
        registry, ctx, hooks, storage, store, lifecycle = environment(tmp_path)
        stopped = []

        @hook_handler("dev.lifecycle:handlers/stop", slot=STOP)
        def stop():
            stopped.append(True)
            ctx.set(VALUE, "final")

        registry.register(entry_from(stop, provider="测试插件"))
        hooks.connect(STOP, Id("dev.lifecycle:handlers/stop"), slot_instance="app", handler_instance="app")
        await lifecycle.start()
        save = store.save

        def fail(snapshot):
            raise OSError("落盘失败")

        monkeypatch.setattr(store, "save", fail)
        with pytest.raises(OSError, match="落盘失败"):
            await lifecycle.stop()
        assert lifecycle.state == "failed"
        assert ctx.get(VALUE) == "final"
        storage.set("dev.lifecycle", "retry", True)
        monkeypatch.setattr(store, "save", save)
        await lifecycle.stop()
        assert stopped == [True]
        assert store.load()[0].value == "final"
        assert lifecycle.state == "stopped"

    asyncio.run(scenario())


def test_restore_failure_preserves_bad_snapshot_and_closes_resources(tmp_path):
    async def scenario():
        _, ctx, _, storage, store, lifecycle = environment(tmp_path)
        store.path.write_text("invalid JSON", encoding="utf-8")
        with pytest.raises(ValueError):
            await lifecycle.start()
        assert store.path.read_text(encoding="utf-8") == "invalid JSON"
        assert lifecycle.state == "stopped"
        with pytest.raises(RuntimeError, match="关闭"):
            storage.keys("dev.lifecycle")
        with pytest.raises(RuntimeError, match="关闭"):
            ctx.list()

    asyncio.run(scenario())


def test_shutdown_drains_writers_before_final_snapshot_and_resource_release(tmp_path):
    async def scenario():
        trace = []
        entered = Event()
        release_io = Event()
        work_entered = asyncio.Event()
        release_work = asyncio.Event()
        gate_closed = asyncio.Event()
        registry = bootstrap()
        install_lifecycle_slots(registry)
        registry.register(RegistryEntry(VALUE, "state_key", StateKey(), "shutdown"))

        class TracedContext(Context):
            def close(self):
                super().close()
                trace.append("ctx:closed")

        class TracedStorage(StorageService):
            def close(self):
                super().close()
                trace.append("storage:closed")

        class TracedStore(JsonSnapshotStore):
            def save(self, snapshot):
                if not entered.is_set():
                    entered.set()
                    if not release_io.wait(5):
                        raise TimeoutError("未释放测试 I/O")
                super().save(snapshot)
                trace.append(f"saved:{snapshot.revision}")

        ctx = TracedContext(registry)
        hooks = HookConnections(registry)
        storage = TracedStorage(tmp_path)
        store = TracedStore(storage.snapshot_store().path)
        persistence = ContextPersistence(ctx, store, interval=3600)
        changes = []
        ctx.subscribe(lambda change: changes.append(change))

        def close_gate():
            trace.append("gate:closed")
            gate_closed.set()

        @hook_handler("dev.lifecycle:handlers/stop", slot=STOP)
        def stop():
            storage.set("dev.lifecycle", "stopped", True)
            ctx.set(VALUE, "stopped")
            trace.append("component:stopped")

        registry.register(entry_from(stop, provider="shutdown"))
        hooks.connect(STOP, Id("dev.lifecycle:handlers/stop"), slot_instance="app", handler_instance="app")
        lifecycle = Lifecycle(
            ctx, hooks, [LifecycleComponent("app", stop_accepting=close_gate)], persistence=persistence, storage=storage
        )
        await lifecycle.start()
        ctx.set(VALUE, "initial")
        flush = asyncio.create_task(persistence.flush())

        async def work(index):
            work_entered.set()
            await release_work.wait()
            ctx.set(VALUE, index, location={"writer": str(index)})
            trace.append(f"work:{index}")

        workers = []
        stopping = None
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            workers = [asyncio.create_task(lifecycle.run(work, index)) for index in range(20)]
            await asyncio.wait_for(work_entered.wait(), 3)
            stopping = asyncio.create_task(lifecycle.stop())
            await asyncio.wait_for(gate_closed.wait(), 3)
            with pytest.raises(RuntimeError, match="新工作"):
                await lifecycle.run(lambda: None)
            release_work.set()
            await asyncio.gather(*workers)
            # stop handler 必须已经结束才能解除磁盘屏障。
            async with asyncio.timeout(3):
                while "component:stopped" not in trace:
                    await asyncio.sleep(0)
            assert "storage:closed" not in trace
            assert ctx.get(VALUE) == "stopped"
        finally:
            release_work.set()
            release_io.set()
            await flush
            if stopping is not None:
                await stopping
            else:
                await lifecycle.stop()
        assert trace[0] == "gate:closed"
        component_index = trace.index("component:stopped")
        assert all(trace.index(f"work:{index}") < component_index for index in range(20))
        assert trace[-3:] == ["saved:22", "storage:closed", "ctx:closed"]
        assert [change.revision for change in changes] == list(range(1, 23))
        assert changes[-1].value == "stopped"
        with pytest.raises(RuntimeError, match="关闭"):
            hooks.for_slot(STOP, "app")
        restored = Context(registry)
        restored.restore(store.load())
        assert restored.get(VALUE) == "stopped"
        assert all(restored.get(VALUE, location={"writer": str(index)}) == index for index in range(20))
        restored.close()
        with StorageService(tmp_path) as reopened:
            assert reopened.get("dev.lifecycle", "stopped") is True

    asyncio.run(scenario())
