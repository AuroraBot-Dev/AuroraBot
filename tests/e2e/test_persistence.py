"""验证异步自动写入、恢复、取消及落盘失败重试。"""

import asyncio
from pathlib import Path
from threading import Event

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, ContextSnapshot, StateKey
from aurora_core.ids import Id
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.snapshots import JsonSnapshotStore

KEY = Id("dev.example:state/data")


def make_context() -> Context:
    registry = bootstrap()
    registry.register(RegistryEntry(KEY, "state_key", StateKey(), "测试插件"))
    return Context(registry)


class ObservedStore(JsonSnapshotStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.saved = Event()
        self.entered = Event()
        self.release = Event()
        self.block = False
        self.fail = False
        self.writes = 0

    def save(self, snapshot: ContextSnapshot) -> None:
        self.entered.set()
        if self.block and not self.release.wait(timeout=5):
            raise TimeoutError("测试未释放写入")
        if self.fail:
            raise OSError("模拟存储故障")
        super().save(snapshot)
        self.writes += 1
        self.saved.set()


async def wait_for(event: Event) -> None:
    assert await asyncio.to_thread(event.wait, 3), "等待存储事件超时"


def test_automatic_save_and_final_changes_restore(tmp_path):
    async def scenario():
        ctx = make_context()
        store = ObservedStore(tmp_path / "state.json")
        persistence = ContextPersistence(ctx, store, interval=0.01)
        await persistence.start()
        ctx.set(KEY, "自动保存")
        await wait_for(store.saved)
        assert store.load()[0].value == "自动保存"
        ctx.set(KEY, "最后修改")
        await persistence.close()
        await persistence.close()
        ctx.close()
        restored = make_context()
        next_run = ContextPersistence(restored, store)
        await next_run.start()
        assert restored.get(KEY) == "最后修改"
        restored.delete(KEY)
        await next_run.close()
        restored.close()
        assert store.load() == ()

    asyncio.run(scenario())


def test_changes_during_write_are_saved_by_same_flush(tmp_path):
    async def scenario():
        ctx = make_context()
        store = ObservedStore(tmp_path / "state.json")
        store.block = True
        persistence = ContextPersistence(ctx, store, interval=3600)
        await persistence.start()
        ctx.set(KEY, "第一份")
        task = asyncio.create_task(persistence.flush())
        try:
            await wait_for(store.entered)
            ctx.set(KEY, "写入期间的新值")
        finally:
            store.release.set()
        await task
        assert store.writes == 2
        assert store.load()[0].value == "写入期间的新值"
        await persistence.close()

    asyncio.run(scenario())


def test_cancelled_flush_waits_for_io_before_next_write(tmp_path):
    async def scenario():
        ctx = make_context()
        store = ObservedStore(tmp_path / "state.json")
        store.block = True
        persistence = ContextPersistence(ctx, store, interval=3600)
        await persistence.start()
        ctx.set(KEY, "旧值")
        task = asyncio.create_task(persistence.flush())
        try:
            await wait_for(store.entered)
            task.cancel()
            ctx.set(KEY, "新值")
            following = asyncio.create_task(persistence.flush())
        finally:
            store.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await following
        assert store.load()[0].value == "新值"
        await persistence.close()

    asyncio.run(scenario())


def test_failed_close_can_retry_without_losing_changes(tmp_path):
    async def scenario():
        ctx = make_context()
        store = ObservedStore(tmp_path / "state.json")
        persistence = ContextPersistence(ctx, store, interval=3600)
        await persistence.start()
        ctx.set(KEY, "保留")
        store.fail = True
        with pytest.raises(OSError, match="存储故障"):
            await persistence.close()
        assert isinstance(persistence.last_error, OSError)
        assert ctx.get(KEY) == "保留"
        ctx.set(KEY, "重试值")
        store.fail = False
        await persistence.close()
        assert persistence.last_error is None
        assert store.load()[0].value == "重试值"

    asyncio.run(scenario())


def test_background_failure_is_reported_and_retried(tmp_path, caplog):
    async def scenario():
        ctx = make_context()
        store = ObservedStore(tmp_path / "state.json")
        store.fail = True
        persistence = ContextPersistence(ctx, store, interval=0.01)
        await persistence.start()
        ctx.set(KEY, "待重试")

        async def failed():
            while persistence.last_error is None:
                await asyncio.sleep(0.001)

        await asyncio.wait_for(failed(), timeout=3)
        store.fail = False
        await wait_for(store.saved)
        await persistence.close()
        assert store.load()[0].value == "待重试"
        assert "自动落盘失败" in caplog.text

    asyncio.run(scenario())


def test_corrupt_start_does_not_overwrite_file_or_mutate_ctx(tmp_path):
    async def scenario():
        ctx = make_context()
        path = tmp_path / "state.json"
        path.write_text("损坏", encoding="utf-8")
        persistence = ContextPersistence(ctx, JsonSnapshotStore(path))
        with pytest.raises(ValueError):
            await persistence.start()
        assert ctx.list() == ()
        assert path.read_text(encoding="utf-8") == "损坏"

    asyncio.run(scenario())


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_invalid_interval_is_rejected(tmp_path, interval):
    with pytest.raises(ValueError, match="间隔"):
        ContextPersistence(make_context(), JsonSnapshotStore(tmp_path / "state.json"), interval=interval)
