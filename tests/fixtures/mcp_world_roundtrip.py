"""无 bot/agent 的 MCP 通知、world 去重和恢复验收；仅启动本机测试服务。"""

import asyncio
import json
import socket
import sys
from pathlib import Path
from typing import cast

import uvicorn
from aurora_adapter.mcp import CLIENT_STATUS, MCPClients
from aurora_adapter.mcp.world import WORLD_SOURCE, WORLD_STATUS, mcp_world_component
from aurora_config import configuration_component
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.storage import StorageService
from aurora_world import RECORDS, SOURCE_STATUS, WorldRecords
from mcp.server import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus
from mcp.shared.subscriptions import ResourceUpdated, ToolsListChanged


class CountingBus(InMemorySubscriptionBus):
    def __init__(self):
        super().__init__()
        self.opened = 0
        self.active = 0

    def subscribe(self, listener):
        self.opened += 1
        self.active += 1
        unsubscribe = super().subscribe(listener)
        closed = False

        def close():
            nonlocal closed
            if not closed:
                self.active -= 1
                closed = True
            unsubscribe()

        return close


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.005)


async def run(root: Path) -> dict:
    bus = CountingBus()
    service = MCPServer("aurora-world-test", subscriptions=bus)
    event = {"message_id": "stable-1", "payload": {"text": "外部原文"}}
    reads = []

    @service.resource("test://event")
    def business_event() -> str:
        """读取具有稳定身份的最新事件。"""
        reads.append("event")
        return json.dumps(event, ensure_ascii=False)

    @service.resource("test://observation")
    def observation() -> str:
        """读取普通资源当前值。"""
        reads.append("observation")
        return "资源当前值"

    @service.tool()
    def echo(text: str) -> str:
        """用于验证来源结束后共享客户端仍然可用。"""
        return text

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            service.streamable_http_app(),
            log_level="critical",
            lifespan="on",
            timeout_graceful_shutdown=1,
        )
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        await until(lambda: server.started or serving.done())
        assert server.started
        first_record = None
        counts = []
        for cycle in range(2):
            registry = bootstrap()
            install_lifecycle_slots(registry)
            register_plugins(
                registry,
                load_plugins(
                    enabled=[
                        "aurora_config",
                        "aurora_world",
                        "aurora_world.configuration",
                        "aurora_adapter.mcp",
                        "aurora_adapter.mcp.world",
                    ]
                ),
            )
            ctx, hooks, storage = Context(registry), HookConnections(registry), StorageService(root)
            directory = storage.configuration_directory()
            connection_path = directory / "org.aurora.adapter" / "mcp.toml"
            source_path = directory / "org.aurora.world" / "config.toml"
            connection_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.parent.mkdir(parents=True, exist_ok=True)
            connection_path.write_text(
                f'schema_version=2\n[servers.local]\ntype="remote"\nprotocol="2026-07-28"\nurl="http://127.0.0.1:{port}/mcp"\ntimeout.execution=10\n',
                encoding="utf-8",
            )
            selection = ""
            for identity, mode in (("event", "event"), ("observation", "resource")):
                selection += (
                    f'[[sources]]\nsource="{WORLD_SOURCE}"\nsource_id="{identity}"\n'
                    '[sources.config]\nconnection_id="local"\nwatch_tools=true\n'
                    f'[[sources.config.resources]]\nuri="test://{identity}"\nmode="{mode}"\n'
                )
            source_path.write_text(selection, encoding="utf-8")
            clients = MCPClients(ctx, hooks, instance_id="test/mcp")
            records = WorldRecords(ctx, storage)
            sources = mcp_world_component(ctx, hooks, clients, records, depends_on=("aurora_world/records",))
            store = storage.snapshot_store()
            host = Lifecycle(
                ctx,
                hooks,
                [
                    records.component(hooks),
                    sources,
                    clients.component(),
                    configuration_component(registry, ctx, hooks, storage),
                ],
                persistence=ContextPersistence(ctx, store, interval=60),
                storage=storage,
            )
            event["message_id"] = "stable-1"
            before_reads = len(reads)
            await host.start()

            def status(identity, ctx=ctx):
                return cast(dict, ctx.get(WORLD_STATUS, location={"source_id": identity}))

            try:
                restored = records.read()
                previous_count = len(restored)
                event_exists = any(record.source_id == "event" for record in restored)
                if event_exists and first_record is None:
                    first_record = next(record.record_id for record in restored if record.source_id == "event")
                assert len(reads) == before_reads and bus.active == 2
                assert status("event")["phase"] == status("observation")["phase"] == "listening"
                await bus.publish(ResourceUpdated(uri="test://event"))
                await until(lambda: status("event")["accepted"] + status("event")["duplicates"] == 1)
                await bus.publish(ResourceUpdated(uri="test://event"))
                await until(lambda event_exists=event_exists: status("event")["duplicates"] == int(event_exists) + 1)
                await bus.publish(ResourceUpdated(uri="test://observation"))
                await until(lambda: status("observation")["accepted"] == 1)
                await bus.publish(ToolsListChanged())
                await until(lambda: status("event")["tools_dirty"] and status("observation")["tools_dirty"])
                current = records.read()
                expected_count = previous_count + 1 + int(not event_exists)
                assert len(current) == expected_count
                assert all(record.source_id in ("event", "observation") for record in current)
                assert cast(dict, current[0].payload)["payload"] == {"text": "外部原文"}
                if first_record is None:
                    first_record = current[0].record_id
                assert current[0].record_id == first_record
                counts.append(len(current))
                if cycle == 0:
                    event["message_id"] = ""
                    await bus.publish(ResourceUpdated(uri="test://event"))
                    await until(lambda: status("event")["error"] == "event_identity_missing")
                    await until(
                        lambda ctx=ctx: (
                            cast(dict, ctx.get(SOURCE_STATUS, location={"source_id": "event"}))["status"] == "failed"
                        )
                    )
                    async with clients.connection("local") as client:
                        assert not (await client.call_tool("echo", {"text": "仍可调用"})).is_error
                    assert (
                        cast(dict, ctx.get(CLIENT_STATUS, location={"owner": "test/mcp", "connection_id": "local"}))[
                            "error"
                        ]
                        is None
                    )
                    assert status("observation")["phase"] == "listening"
                else:
                    server.should_exit = True
                    await serving
                    await until(lambda: bool(status("event")["error"]) and bool(status("observation")["error"]))
                    assert status("event")["error"] in {"subscription_ended", "subscription_lost"}
                    assert bus.opened == 4
                assert len(records.read()) == expected_count
            finally:
                await host.stop()
            await until(lambda: bus.active == 0)
            assert all(record.address.key == RECORDS for record in store.load())
            assert source_path.read_text(encoding="utf-8") == selection
        assert not [
            task
            for task in asyncio.all_tasks()
            if task.get_name().startswith(("aurora-mcp:", "mcp-world:", "world-source:"))
        ]
        return {
            "counts": counts,
            "stable_record": True,
            "record_id": first_record,
            "shared_client": True,
            "disconnect_reported": True,
            "subscriptions": bus.opened,
        }
    finally:
        server.should_exit = True
        await serving
        listener.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(Path(sys.argv[1]))), ensure_ascii=False))
