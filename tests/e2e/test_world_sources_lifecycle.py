"""验证来源实例与真实宿主的启动、失败收尾、取消及最终落盘。"""

import asyncio
from typing import cast

import pytest
from aurora_core import Id
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from aurora_world import SOURCES, SourceInstance, SourceSpec, SourceUnavailableError, WorldRecords, WorldSources
from aurora_world.plugin import plugin


def environment(root, *, failure=None, source="b", block=None):
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, [plugin()])
    ctx, hooks = Context(registry), HookConnections(registry)
    storage = StorageService(root)
    records = WorldRecords(ctx, storage)
    store = storage.snapshot_store()
    events, captures, failed = [], {}, set()
    entered = asyncio.Event()

    async def phase(name, source_id):
        events.append((source_id, name))
        if (name, source_id) == (block, source):
            entered.set()
            await asyncio.Event().wait()
        if (name, source_id) == (failure, source) and name not in failed:
            failed.add(name)
            raise RuntimeError(f"来源 {source_id} {name} 失败")

    async def factory(*, source_id, emit, config):
        captures[source_id] = emit
        with pytest.raises(SourceUnavailableError):
            emit(message_id="prepare", payload=None)
        try:
            await phase("prepare", source_id)
        except BaseException:
            events.append((source_id, "factory.closed"))
            raise

        async def start():
            emit(message_id="first", payload=source_id)
            await phase("start", source_id)

        async def stop():
            with pytest.raises(SourceUnavailableError):
                emit(message_id="stop", payload=None)
            await phase("stop", source_id)

        async def close():
            with pytest.raises(SourceUnavailableError):
                emit(message_id="close", payload=None)
            await phase("close", source_id)

        return SourceInstance(start, stop, close)

    identity = Id("dev.sources:sources/lifecycle")
    registry.register(RegistryEntry(identity, "source", SourceSpec(factory), "test", register_to=SOURCES))
    sources = WorldSources(ctx, hooks, records)
    for name in ("a", "b"):
        sources.add(identity, source_id=name)
    host = Lifecycle(
        ctx,
        hooks,
        [records.component(hooks), sources.component(depends_on=("aurora_world/records",))],
        persistence=ContextPersistence(ctx, store, interval=60),
        storage=storage,
    )
    return host, ctx, store, events, captures, entered


def assert_closed(host, ctx, captures):
    assert host.state == "stopped"
    with pytest.raises(RuntimeError, match="关闭"):
        ctx.list()
    for emit in captures.values():
        with pytest.raises(SourceUnavailableError):
            emit(message_id="after-close", payload=None)


@pytest.mark.parametrize("source", ["a", "b"])
@pytest.mark.parametrize("failure", ["prepare", "start"])
def test_start_failure_closes_all_owned_instances_and_keeps_accepted_records(tmp_path, source, failure):
    async def scenario():
        host, ctx, store, events, captures, _ = environment(tmp_path, failure=failure, source=source)
        try:
            with pytest.raises(RuntimeError, match=f"{source} {failure} 失败"):
                await host.start()
        finally:
            await host.stop()
        assert_closed(host, ctx, captures)
        if failure == "prepare":
            assert (source, "factory.closed") in events
            assert not any(phase == "start" for _, phase in events)
            assert [(name, phase) for name, phase in events if phase == "close"] == (
                [("a", "close")] if source == "b" else []
            )
            assert store.load() == ()
        else:
            count = 1 if source == "a" else 2
            assert len(cast(dict, store.load()[0].value)["records"]) == count
            assert events.count(("a", "stop")) == 1
            assert events.count(("b", "stop")) == (source == "b")
            assert events[-2:] == [("b", "close"), ("a", "close")]

    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["a", "b"])
@pytest.mark.parametrize("failure", ["stop", "close"])
def test_shutdown_failure_preserves_resources_for_retry_without_repeating_completed_actions(tmp_path, source, failure):
    async def scenario():
        host, ctx, store, events, captures, _ = environment(tmp_path, failure=failure, source=source)
        await host.start()
        try:
            with pytest.raises(RuntimeError, match=f"{source} {failure} 失败"):
                await host.stop()
            assert host.state == "failed"
            assert ctx.list()
            for emit in captures.values():
                with pytest.raises(SourceUnavailableError):
                    emit(message_id="retry", payload=None)
            if failure == "stop":
                assert not any(phase == "close" for _, phase in events)
        finally:
            await host.stop()
        assert_closed(host, ctx, captures)
        for name in ("a", "b"):
            for phase in ("prepare", "start", "stop", "close"):
                assert events.count((name, phase)) == (2 if (name, phase) == (source, failure) else 1)
        assert [record["source_id"] for record in cast(dict, store.load()[0].value)["records"]] == ["a", "b"]
        completed = list(events)
        await host.stop()
        assert events == completed

    asyncio.run(scenario())


@pytest.mark.parametrize("block", ["prepare", "start"])
def test_cancelled_start_releases_partial_sources_and_revokes_retained_callbacks(tmp_path, block):
    async def scenario():
        host, ctx, store, events, captures, entered = environment(tmp_path, block=block)
        task = asyncio.create_task(host.start())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await host.stop()
        assert_closed(host, ctx, captures)
        if block == "prepare":
            assert ("b", "factory.closed") in events and events[-1] == ("a", "close")
            assert store.load() == ()
        else:
            assert events[-4:] == [("b", "stop"), ("a", "stop"), ("b", "close"), ("a", "close")]
            assert len(cast(dict, store.load()[0].value)["records"]) == 2

    asyncio.run(scenario())
