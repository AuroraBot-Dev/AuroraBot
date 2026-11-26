"""验证 TOML 装配、后台观察、失败隔离及关闭时资源与快照顺序。"""

import asyncio
from typing import cast

import pytest
from aurora_config import configuration_component
from aurora_core import Id
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from aurora_world import (
    RECORDS,
    SOURCE_STATUS,
    SOURCES,
    SourceInstance,
    SourceSpec,
    SourceUnavailableError,
    WorldRecords,
)
from aurora_world.configuration import CONFIG_STATE, configured_sources_component

SOURCE = Id("dev.test:sources/configured")


def environment(root, factory, text=None, *, timeout=1.0):
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, load_plugins(enabled=["aurora_config", "aurora_world", "aurora_world.configuration"]))
    registry.register(RegistryEntry(SOURCE, "source", SourceSpec(factory), "test", register_to=SOURCES))
    ctx, hooks, storage = Context(registry), HookConnections(registry), StorageService(root)
    records = WorldRecords(ctx, storage)
    path = storage.configuration_directory() / "org.aurora.world" / "config.toml"
    if text is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    store = storage.snapshot_store()
    host = Lifecycle(
        ctx,
        hooks,
        [
            records.component(hooks),
            configured_sources_component(ctx, hooks, records, depends_on=("aurora_world/records",)),
            configuration_component(registry, ctx, hooks, storage),
        ],
        persistence=ContextPersistence(ctx, store, interval=60),
        storage=storage,
        timeout=timeout,
    )
    return host, ctx, store, path


def declaration(name, source=SOURCE):
    return f'[[sources]]\nsource = "{source}"\nsource_id = "{name}"\n[sources.config]\nlabel = "{name}"\n'


async def noop():
    pass


@pytest.mark.parametrize("selection", ["empty", "unknown", "selected"])
def test_selection_precedes_all_factories_and_configuration_is_not_persisted(tmp_path, selection):
    async def scenario():
        captures = []

        async def factory(*, source_id, emit, config):
            captures.append((source_id, config))
            assert cast(dict, ctx.get(CONFIG_STATE))["sources"][0]["source_id"] == "chosen"

            async def start():
                emit(message_id="first", payload=config)

            return SourceInstance(start, noop, noop)

        text = None if selection == "empty" else declaration("chosen")
        if selection == "unknown":
            assert text is not None
            text += declaration("missing", Id("dev.test:sources/missing"))
        host, ctx, store, path = environment(tmp_path, factory, text)
        if selection == "unknown":
            with pytest.raises(KeyError):
                await host.start()
            assert captures == []
        else:
            await host.start()
            assert captures == ([] if selection == "empty" else [("chosen", {"label": "chosen"})])
            ctx.set(CONFIG_STATE, {"sources": []})
        original = path.read_text(encoding="utf-8")
        await host.stop()
        assert path.read_text(encoding="utf-8") == original
        if text is not None:
            assert original == text
        assert all(item.address.key == RECORDS for item in store.load())

    asyncio.run(scenario())


@pytest.mark.parametrize("ending", ["return", "raise", "cancel"])
def test_background_exit_closes_only_its_source_and_observes_error(tmp_path, ending, caplog):
    async def scenario():
        unhandled = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: unhandled.append(context))
        captures, tasks = {}, {}
        entered, release = asyncio.Event(), asyncio.Event()

        async def factory(*, source_id, emit, config):
            captures[source_id] = emit

            async def run():
                tasks[source_id] = asyncio.current_task()
                if source_id == "healthy":
                    await asyncio.Event().wait()
                entered.set()
                await release.wait()
                if ending == "raise":
                    raise RuntimeError("secret-runtime-credential")
                if ending == "cancel":
                    raise asyncio.CancelledError

            return SourceInstance(noop, noop, noop, run)

        host, ctx, store, _ = environment(tmp_path, factory, declaration("bad") + declaration("healthy"))
        await host.start()
        await entered.wait()
        release.set()
        await asyncio.wait({tasks["bad"]})
        with pytest.raises(SourceUnavailableError):
            captures["bad"](message_id="late", payload=None)
        captures["healthy"](message_id="alive", payload=True)
        state = cast(dict, ctx.get(SOURCE_STATUS, location={"source_id": "bad"}))
        assert state["accepting"] is False
        assert state["status"] == ("completed" if ending == "return" else "failed")
        assert (
            state["error"] == {"return": None, "raise": "background_failed", "cancel": "background_cancelled"}[ending]
        )
        assert "secret-runtime-credential" not in str(state) + caplog.text
        assert len(cast(dict, ctx.get(RECORDS))["records"]) == 1
        await host.stop()
        assert all(task.done() for task in tasks.values())
        assert [item.address.key for item in store.load()] == [RECORDS]
        await asyncio.sleep(0)
        assert unhandled == []

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_partial_start_failure_waits_for_already_running_source(tmp_path, cancel):
    async def scenario():
        entered = asyncio.Event()
        events = []

        async def factory(*, source_id, emit, config):
            async def start():
                if source_id == "b":
                    await entered.wait()
                    if cancel:
                        raise asyncio.CancelledError
                    raise RuntimeError("start failed")

            async def run():
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    events.append("run.finished")

            async def close():
                assert "run.finished" in events
                events.append(source_id + ".closed")

            return SourceInstance(start, noop, close, run)

        host, _, store, _ = environment(tmp_path, factory, declaration("a") + declaration("b"))
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await host.start()
        await host.stop()
        assert events == ["run.finished", "b.closed", "a.closed"]
        assert store.load() == ()

    asyncio.run(scenario())


@pytest.mark.parametrize("stop_failure", [False, True])
def test_shutdown_preserves_resources_until_background_finally_finishes(tmp_path, stop_failure):
    async def scenario():
        entered, finishing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        events = []

        async def factory(*, source_id, emit, config):
            async def run():
                entered.set()
                emit(message_id="accepted", payload=True)
                try:
                    await asyncio.Event().wait()
                finally:
                    finishing.set()
                    await release.wait()
                    events.append("run.finished")

            async def stop():
                events.append("stop")
                if stop_failure and events.count("stop") == 1:
                    raise RuntimeError("stop failed")

            async def close():
                assert "run.finished" in events
                events.append("close")

            return SourceInstance(noop, stop, close, run)

        host, ctx, store, _ = environment(tmp_path, factory, declaration("a"), timeout=0.05)
        await host.start()
        await entered.wait()
        with pytest.raises(RuntimeError if stop_failure else TimeoutError):
            await host.stop()
        await finishing.wait()
        assert "close" not in events
        assert host.state == "failed"
        assert cast(dict, ctx.get(SOURCE_STATUS, location={"source_id": "a"}))["accepting"] is False
        retry = asyncio.create_task(host.stop())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert "close" not in events
        release.set()
        await retry
        assert events[-2:] == ["run.finished", "close"]
        assert events.count("stop") == (2 if stop_failure else 1)
        assert len(store.load()) == 1

    asyncio.run(scenario())
