"""验证资源通知的身份语义、有界接纳与来源独立收尾。"""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from aurora_adapter.mcp.clients import MCPClients
from aurora_adapter.mcp.configuration import PROTOCOL_VERSION
from aurora_adapter.mcp.world import (
    WORLD_SOURCE,
    WORLD_STATUS,
    MCPWorldError,
    _ResourceSource,
    mcp_world_component,
    plugin,
)
from aurora_adapter.mcp.world_config import WORLD_CONFIG
from aurora_config import configuration_component
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import Lifecycle, LifecycleComponent, install_lifecycle_slots
from aurora_core.storage import StorageService
from aurora_world import WorldRecords
from aurora_world.plugin import plugin as world_plugin
from aurora_world.sources import SourceSpec
from mcp.client.subscriptions import ResourceUpdated, SubscriptionLost, ToolsListChanged
from mcp.types import BlobResourceContents, TextResourceContents

URI = "test://one"


def values(**kwargs):
    return {"connection_id": "local", "resources": [{"uri": URI}], **kwargs}


class FakeClient:
    instance_id = "client"

    def __init__(self):
        self.protocol_version = PROTOCOL_VERSION
        self.events = asyncio.Queue()
        self.entered = asyncio.Event()
        self.closed = asyncio.Event()
        self.release_close = asyncio.Event()
        self.release_close.set()
        self.reading = asyncio.Event()
        self.release_read = asyncio.Event()
        self.release_read.set()
        self.reads = []
        self.content: TextResourceContents | BlobResourceContents = TextResourceContents(uri=URI, text="resource")
        self.honor = True
        self.release_ack = asyncio.Event()
        self.release_ack.set()
        self.read_error: Exception | None = None
        self.close_error: Exception | None = None
        self.leases = 0
        self.server_capabilities = SimpleNamespace(resources=object(), tools=object())

    @asynccontextmanager
    async def connection(self, identity):
        assert identity == "local"
        self.leases += 1
        try:
            yield self
        finally:
            self.leases -= 1

    @asynccontextmanager
    async def listen(self, *, resource_subscriptions, tools_list_changed):
        self.honored = SimpleNamespace(
            resource_subscriptions=resource_subscriptions if self.honor else [], tools_list_changed=tools_list_changed
        )
        task = asyncio.current_task()
        self.entered.set()
        try:
            await self.release_ack.wait()
            yield self
        finally:
            await self.release_close.wait()
            assert task is asyncio.current_task()
            self.closed.set()
            if self.close_error:
                raise self.close_error

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self.events.get()
        if event is None:
            raise StopAsyncIteration
        if isinstance(event, Exception):
            raise event
        return event

    async def read_resource(self, uri):
        self.reads.append(uri)
        self.reading.set()
        await self.release_read.wait()
        if self.read_error:
            raise self.read_error
        return SimpleNamespace(contents=[self.content])


def environment(client, config=None):
    registry = bootstrap()
    register_plugins(registry, [world_plugin(), plugin()])
    ctx = Context(registry)
    records = WorldRecords(ctx)
    records.open()

    def emit(**kwargs):
        return records.append(source_id="test", **kwargs)

    source = _ResourceSource(ctx, client, "test", emit, cast(dict, WORLD_CONFIG.parse(config or values())))
    return source, ctx, records


def test_legacy_resources_do_not_imply_modern_subscription_support():
    async def scenario():
        client = FakeClient()
        client.protocol_version = "2025-11-25"
        source, ctx, records = environment(client)
        try:
            with pytest.raises(MCPWorldError, match="unsupported_subscription_protocol"):
                await source.start()
            await source.stop()
            assert not client.entered.is_set() and client.leases == 0
            assert records.read() == ()
            assert not source.close_failed
        finally:
            ctx.close()

    asyncio.run(scenario())


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize(
    "config",
    [
        values(resources=[]),
        values(resources=[{"uri": "relative"}]),
        values(resources=[{"uri": URI}, {"uri": URI}]),
        values(resources=[{"uri": URI, "mode": "invented"}]),
    ],
)
def test_invalid_selections_are_rejected(config):
    with pytest.raises(ValueError):
        WORLD_CONFIG.parse(config)


def test_plugin_requires_explicit_dependencies_and_does_not_connect():
    with pytest.raises(ValueError):
        load_plugins(enabled=["aurora_adapter.mcp.world"])
    definitions = plugin().entries
    assert len(definitions) == 2
    assert all(entry.id.namespace == "org.aurora.adapter" for entry in definitions)


def test_world_factory_is_bound_per_host_without_mutating_shared_definition(tmp_path):
    async def scenario():
        record_services = []
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
        definition = cast(SourceSpec, registry.get(WORLD_SOURCE).target).factory
        hosts, clients, contexts = [], [], []
        try:
            for number in range(2):
                ctx, hooks = Context(registry), HookConnections(registry)
                storage = StorageService(tmp_path / str(number))
                world_records = WorldRecords(ctx, storage)
                record_services.append(world_records)
                path = storage.configuration_directory() / "org.aurora.world/config.toml"
                path.parent.mkdir(parents=True)
                path.write_text(
                    f'[[sources]]\nsource="{WORLD_SOURCE}"\nsource_id="shared"\n'
                    f'[sources.config]\nconnection_id="local"\nresources=[{{uri="{URI}"}}]\n',
                    encoding="utf-8",
                )
                client = FakeClient()
                host = Lifecycle(
                    ctx,
                    hooks,
                    [
                        world_records.component(hooks),
                        configuration_component(registry, ctx, hooks, storage),
                        LifecycleComponent("client"),
                        mcp_world_component(
                            ctx, hooks, cast(MCPClients, client), world_records, depends_on=("aurora_world/records",)
                        ),
                    ],
                    storage=storage,
                )
                hosts.append(host)
                clients.append(client)
                contexts.append(ctx)
                await host.start()
                assert cast(SourceSpec, registry.get(WORLD_SOURCE).target).factory is definition
            await clients[0].events.put(ResourceUpdated(uri=URI))
            await until(lambda: len(record_services[0].read()) == 1)
            assert record_services[1].read() == ()
            await hosts[0].stop()
            assert clients[0].leases == 0 and clients[1].leases == 1
            await clients[1].events.put(ResourceUpdated(uri=URI))
            await until(lambda: len(record_services[1].read()) == 1)
        finally:
            for host in hosts:
                await host.stop()
        assert cast(SourceSpec, registry.get(WORLD_SOURCE).target).factory is definition
        assert all(client.leases == 0 and client.closed.is_set() for client in clients)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["notification", "resource", "event"])
def test_identity_and_content_are_explicit_and_deduplication_uses_source_identity(mode):
    async def scenario():
        client = FakeClient()
        client.content = TextResourceContents(
            uri=URI, text=json.dumps({"message_id": "remote-1", "payload": {"text": "原文"}})
        )
        source, ctx, records = environment(client, values(resources=[{"uri": URI, "mode": mode}]))
        await source.start()
        assert records.read() == ()
        for count in (1, 2):
            await client.events.put(ResourceUpdated(uri=URI))
            await until(lambda count=count: source.accepted + source.duplicates == count)
        payload = cast(dict, records.read()[0].payload)
        if mode == "event":
            assert len(records.read()) == 1 and source.duplicates == 1
            assert payload["payload"] == {"text": "原文"}
            assert "observed_at" not in payload
        else:
            assert len(records.read()) == 2
            assert records.read()[0].message_id != records.read()[1].message_id
            assert payload["identity"] == "local_observation"
        assert client.reads == ([] if mode == "notification" else [URI, URI])
        assert ("contents" in payload) == (mode == "resource")
        await source.stop()
        assert client.closed.is_set() and client.leases == 0
        assert source.error is None
        ctx.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("missing_id", "event_identity_missing"),
        ("invalid", "invalid_event"),
        ("blob", "invalid_event"),
        ("read", "resource_read_failed"),
        ("size", "resource_too_large"),
        ("conflict", "event_conflict"),
        ("unselected", "unselected_resource"),
        ("lost", "subscription_lost"),
        ("ended", "subscription_ended"),
    ],
)
def test_source_failures_are_diagnostic_and_do_not_emit_or_retry(fault, expected, caplog):
    async def scenario():
        client = FakeClient()
        config = values(resources=[{"uri": URI, "mode": "event"}])
        client.content = TextResourceContents(uri=URI, text='{"message_id":"stable","payload":1}')
        if fault == "missing_id":
            client.content = TextResourceContents(uri=URI, text='{"payload":"secret-text"}')
        if fault == "invalid":
            client.content = TextResourceContents(uri=URI, text="secret-invalid-json")
        if fault == "blob":
            client.content = BlobResourceContents(uri=URI, blob="c2VjcmV0")
        if fault == "read":
            client.read_error = RuntimeError("secret-error")
        if fault == "size":
            config["max_content_bytes"] = 1
        source, ctx, records = environment(client, config)
        await source.start()
        if fault == "conflict":
            await client.events.put(ResourceUpdated(uri=URI))
            await until(lambda: source.accepted == 1)
            client.content = TextResourceContents(uri=URI, text='{"message_id":"stable","payload":2}')
        event = {
            "lost": SubscriptionLost("secret-disconnect"),
            "ended": None,
            "unselected": ResourceUpdated(uri="test://unselected"),
        }.get(fault, ResourceUpdated(uri=URI))
        await client.events.put(event)
        with pytest.raises(MCPWorldError, match=expected):
            await source.run()
        assert len(records.read()) == (1 if fault == "conflict" else 0)
        status = cast(dict, ctx.get(WORLD_STATUS, location={"source_id": "test"}))
        assert status["phase"] == "failed" and status["error"] == expected
        assert "secret" not in str(status) + caplog.text
        await source.stop()
        assert client.leases == 0
        ctx.close()

    asyncio.run(scenario())


def test_overflow_cancels_inflight_read_and_reports_all_uncommitted_inputs():
    async def scenario():
        client = FakeClient()
        client.release_read.clear()
        source, ctx, records = environment(client, values(buffer_size=1))
        await source.start()
        await client.events.put(ResourceUpdated(uri=URI))
        await client.reading.wait()
        await client.events.put(ResourceUpdated(uri=URI))
        await client.events.put(ResourceUpdated(uri=URI))
        with pytest.raises(MCPWorldError, match="buffer_overflow"):
            await source.run()
        assert records.read() == () and source.discarded == 3
        assert client.closed.is_set()
        await source.stop()
        ctx.close()

    asyncio.run(scenario())


def test_tool_catalog_changes_are_not_world_messages_and_unhonored_filter_is_rejected():
    async def scenario():
        client = FakeClient()
        source, ctx, records = environment(client, values(watch_tools=True))
        await source.start()
        await client.events.put(ToolsListChanged())
        await until(lambda: source.tools_dirty)
        assert records.read() == () and client.reads == []
        await source.stop()
        ctx.close()
        client = FakeClient()
        client.honor = False
        source, ctx, _ = environment(client)
        with pytest.raises(MCPWorldError, match="subscription_not_honored"):
            await source.start()
        await source.stop()
        assert client.closed.is_set()
        ctx.close()

    asyncio.run(scenario())


def test_cancelled_close_wait_can_resume_and_does_not_cancel_the_shared_client():
    async def scenario():
        client = FakeClient()
        source, ctx, records = environment(client)
        await source.start()
        client.release_close.clear()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(source.stop(), 0.02)
        assert client.leases == 1
        client.release_close.set()
        await source.stop()
        assert client.closed.is_set() and client.leases == 0 and records.read() == ()
        assert source.error is None
        ctx.close()

    asyncio.run(scenario())


def test_shutdown_reports_pending_work_and_close_failure():
    async def scenario():
        client = FakeClient()
        client.release_read.clear()
        source, ctx, _ = environment(client)
        await source.start()
        await client.events.put(ResourceUpdated(uri=URI))
        await client.reading.wait()
        await source.stop()
        assert source.error == "stopped_with_pending" and source.discarded == 1
        ctx.close()
        client = FakeClient()
        client.close_error = RuntimeError("secret-close-error")
        source, ctx, _ = environment(client)
        await source.start()
        for _ in range(2):
            with pytest.raises(MCPWorldError, match="subscription_close_failed"):
                await source.stop()
        assert source.close_failed
        ctx.close()

    asyncio.run(scenario())


def test_start_cancellation_waits_for_subscription_owner_and_releases_borrow():
    async def scenario():
        client = FakeClient()
        client.release_ack.clear()
        source, ctx, records = environment(client)
        start = asyncio.create_task(source.start())
        await client.entered.wait()
        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start
        await source.stop()
        assert client.closed.is_set() and client.leases == 0
        assert records.read() == () and source.error is None
        ctx.close()

    asyncio.run(scenario())


def test_failure_followed_by_shutdown_is_not_a_close_failure():
    async def scenario():
        client = FakeClient()
        client.release_close.clear()
        source, ctx, records = environment(client)
        await source.start()
        await client.events.put(SubscriptionLost("secret-lost"))
        await until(lambda: source.error == "subscription_lost")
        close = asyncio.create_task(source.stop())
        client.release_close.set()
        await close
        assert not source.close_failed and records.read() == ()
        ctx.close()

    asyncio.run(scenario())


def test_unhonored_subscription_also_reports_failed_cleanup():
    async def scenario():
        client = FakeClient()
        client.honor = False
        client.close_error = RuntimeError("secret-close")
        source, ctx, _ = environment(client)
        with pytest.raises(MCPWorldError, match="subscription_close_failed"):
            await source.start()
        with pytest.raises(MCPWorldError, match="subscription_close_failed"):
            await source.close()
        assert source.close_failed
        ctx.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("capability", ["resources", "tools"])
def test_required_consumer_capability_is_checked_before_listening(capability):
    async def scenario():
        client = FakeClient()
        setattr(client.server_capabilities, capability, None)
        source, ctx, records = environment(client, values(watch_tools=True))
        code = "missing_resource_capability" if capability == "resources" else "missing_tools_capability"
        with pytest.raises(MCPWorldError, match=code):
            await source.start()
        assert not client.entered.is_set() and client.leases == 0
        assert records.read() == ()
        await source.stop()
        ctx.close()

    asyncio.run(scenario())
