"""真实 CLI 进程验收插件：发布状态、触发 SIGINT，并提供收尾故障注入。"""

import asyncio
import os
import signal
from dataclasses import replace

from aurora_core import Id, entry_from, hook_handler
from aurora_core.ctx import StateKey
from aurora_core.discovery import Plugin
from aurora_core.lifecycle import PREPARE, START, STOP, LifecycleComponent
from aurora_core.registry import RegistryEntry
from aurora_core.snapshots import JsonSnapshotStore

KEY = Id("dev.cli_shutdown:state/value")
ASSEMBLY = Id("dev.cli_shutdown:assemblies/watch")


def assemble(*, registry, ctx, hooks, storage, workspace_root):
    fault = os.environ.get("AURORA_CLI_SHUTDOWN_FAULT", "")
    ready = asyncio.Event()
    worker = None
    subscription = None
    trace = storage.directory("dev.cli_shutdown") / "events.txt"

    def record(value):
        with trace.open("a", encoding="utf-8") as stream:
            stream.write(f"{value}\n")

    original = registry.get(Id("org.aurora.core:operations/ctx/subscribe"))

    def subscribe(callback, **filters):
        handle = ctx.subscribe(callback, **filters)
        ready.set()
        return handle

    registry.replace(replace(original, target=subscribe))

    class FailingStore(JsonSnapshotStore):
        def save(self, snapshot):
            raise OSError("CLI 最终落盘故障")

    if fault == "flush":
        path = storage.snapshot_store().path
        storage.snapshot_store = lambda: FailingStore(path)

    @hook_handler("dev.cli_shutdown:handlers/prepare", slot=PREPARE)
    def prepare():
        nonlocal subscription
        subscription = ctx.subscribe(lambda change: record(change.value), key=KEY)

    async def produce():
        await ready.wait()
        ctx.set(KEY, "first")
        await asyncio.sleep(0)
        ctx.set(KEY, "second")
        await asyncio.sleep(0)
        signal.raise_signal(signal.SIGINT)

    @hook_handler("dev.cli_shutdown:handlers/start", slot=START)
    def start():
        nonlocal worker
        worker = asyncio.create_task(produce())

    @hook_handler("dev.cli_shutdown:handlers/stop", slot=STOP)
    async def stop():
        if worker is not None:
            await worker
        if fault == "stop":
            raise RuntimeError("CLI 组件停止故障")
        ctx.set(KEY, "stopped")
        if subscription is not None:
            ctx.unsubscribe(subscription)
        record("source:closed")

    for phase, handler in ((PREPARE, prepare), (START, start), (STOP, stop)):
        entry = entry_from(handler, provider="cli_shutdown_fixture")
        registry.register(entry)
        hooks.connect(phase, entry.id, slot_instance="app", handler_instance="app")
    return [LifecycleComponent("app", stop_accepting=lambda: record("gate:closed"))]


def plugin():
    return Plugin(
        "cli_shutdown_fixture",
        (
            RegistryEntry(KEY, "state_key", StateKey(), "cli_shutdown_fixture"),
            RegistryEntry(ASSEMBLY, "assembly", assemble, "cli_shutdown_fixture"),
        ),
    )
