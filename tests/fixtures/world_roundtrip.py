"""验证 core/world 的程序装配或可选 config 装配及快照往返。"""

import asyncio
import json
import sys
from pathlib import Path

from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.declarations import plug_id
from aurora_core.discovery import load_plugins, register_plugins
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


def wire(hooks, identity, bindings, *, depends_on=(), stop_accepting=None):
    for phase, method in bindings:
        hooks.connect(phase, plug_id(method), slot_instance=identity, handler_instance=identity, target=method)
    return LifecycleComponent(identity, depends_on=depends_on, stop_accepting=stop_accepting)


def configured_world(ctx, hooks, records, *, depends_on=(), clients=None):
    from aurora_world.configuration import _SourceConfiguration
    from aurora_world.sources import WorldSources

    sources = WorldSources(ctx, records)
    configuration = _SourceConfiguration(ctx)
    resources = {}
    if clients is not None:
        from aurora_mcp.world import WORLD_SOURCE

        resources = {str(WORLD_SOURCE): {"ctx": ctx, "clients": clients}}
        depends_on = (*depends_on, clients.instance_id)
    configuration.bind(sources=sources, source_resources=resources)
    return wire(
        hooks,
        "aurora_world/sources",
        (
            (CONFIG, configuration.configure),
            (PREPARE, sources.prepare),
            (START, sources.start),
            (STOP, sources.stop),
            (CLEAN, sources.clean),
        ),
        depends_on=("aurora_config", *depends_on),
        stop_accepting=sources.stop_accepting,
    )


def configuration_component(registry, ctx, hooks, storage):
    from aurora_config._meta import LOAD
    from aurora_config.service import ConfigurationService
    from aurora_core.lifecycle import CONFIG, LifecycleComponent

    service = ConfigurationService(registry, ctx, storage)
    hooks.connect(
        CONFIG, LOAD, slot_instance="aurora_config", handler_instance="aurora_config", target=service.configure
    )
    return LifecycleComponent("aurora_config", stop_accepting=service.close)


async def main(root, *, configured=False):
    registry = bootstrap()
    enabled = ["aurora_world.records", "aurora_world.sources"]
    if configured:
        enabled.extend(("aurora_config", "aurora_world.configuration"))
    register_plugins(registry, load_plugins(enabled=enabled))
    install_lifecycle_slots(registry)
    ctx = Context(registry)
    hooks = HookConnections(registry)
    emitters = []

    async def factory(*, source_id, emit, config, resources):
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
        from aurora_config import copy_missing

        copy_missing(
            storage.configuration_directory() / "org.aurora.world" / "plugin.config.toml",
            f'[[sources]]\nsource = "{identity}"\nsource_id = "workshop/sensor"\n'.encode(),
        )
        components = [
            configured_world(ctx, hooks, records, depends_on=("aurora_world/records",)),
            configuration_component(registry, ctx, hooks, storage),
        ]
    else:
        sources = WorldSources(ctx, records)
        sources.add(identity, source_id="workshop/sensor")
        components = [
            wire(
                hooks,
                "aurora_world/sources",
                (
                    (PREPARE, sources.prepare),
                    (START, sources.start),
                    (STOP, sources.stop),
                    (CLEAN, sources.clean),
                ),
                depends_on=("aurora_world/records",),
                stop_accepting=sources.stop_accepting,
            )
        ]
    store = storage.snapshot_store()
    host = Lifecycle(
        ctx,
        hooks,
        [
            wire(
                hooks,
                "aurora_world/records",
                (
                    (PREPARE, records.prepare),
                    (START, records.start),
                    (STOP, records.stop),
                    (CLEAN, records.clean),
                ),
                depends_on=(),
                stop_accepting=None,
            ),
            *components,
        ],
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
