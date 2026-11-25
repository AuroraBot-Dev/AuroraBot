"""验证 core/world 的程序装配或可选 config 装配及快照往返。"""

import asyncio
import json
import sys
from pathlib import Path

from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from aurora_world import (
    RECORDS,
    SOURCES,
    SourceInstance,
    SourceSpec,
    SourceUnavailableError,
    WorldRecords,
    WorldSources,
)


async def main(root, *, configured=False):
    registry = bootstrap()
    enabled = ["aurora_world"]
    if configured:
        enabled.extend(("aurora_config", "aurora_world.configuration"))
    register_plugins(registry, load_plugins(enabled=enabled))
    install_lifecycle_slots(registry)
    ctx = Context(registry)
    hooks = HookConnections(registry)
    emitters = []

    async def factory(*, source_id, emit, config):
        emitters.append(emit)

        async def start():
            pass

        async def stop():
            pass

        return SourceInstance(start, stop, stop)

    identity = Id("dev.world:sources/manual")
    registry.register(RegistryEntry(identity, "source", SourceSpec(factory), "test", register_to=SOURCES))
    storage = StorageService(root)
    records = WorldRecords(ctx, storage)
    if configured:
        from aurora_config import configuration_component, copy_missing
        from aurora_world.configuration import configured_sources_component

        copy_missing(
            storage.configuration_directory() / "org.aurora.world" / "config.toml",
            f'[[sources]]\nsource = "{identity}"\nsource_id = "workshop/sensor"\n'.encode(),
        )
        components = [
            configured_sources_component(ctx, hooks, records, depends_on=("aurora_world/records",)),
            configuration_component(registry, ctx, hooks, storage),
        ]
    else:
        sources = WorldSources(ctx, hooks, records)
        sources.add(identity, source_id="workshop/sensor")
        components = [sources.component(depends_on=("aurora_world/records",))]
    store = storage.snapshot_store()
    host = Lifecycle(
        ctx,
        hooks,
        [records.component(hooks), *components],
        persistence=ContextPersistence(ctx, store, interval=60),
        storage=storage,
    )
    await host.start()
    observed = []
    handle = ctx.subscribe(observed.append, key=RECORDS, location={})
    try:
        before = records.read()
        receipt = emitters[0](message_id="first", payload={"text": "世界变化"})
        assert receipt.duplicate is bool(before)
        if before:
            assert receipt.record == before[0]
        new = emitters[0](message_id=f"next-{len(before)}", payload=None)
        assert not new.duplicate
        assert len(observed) == (1 if before else 2)
        assert records.read(after=receipt.record.position)[-1] == new.record
        result = {
            "duplicate": receipt.duplicate,
            "journal_id": receipt.record.position.journal_id,
            "first_id": receipt.record.record_id,
            "sequences": [record.position.sequence for record in records.read()],
        }
    finally:
        assert ctx.unsubscribe(handle)
        await host.stop()
    try:
        emitters[0](message_id="late", payload=None)
    except SourceUnavailableError:
        pass
    else:
        raise AssertionError("关闭后仍接纳来源消息")
    assert all(record.address.key == RECORDS for record in store.load())
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), configured="--configured" in sys.argv[2:]))
