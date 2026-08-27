from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from src.contracts import (
    MCP_APP_DISCONNECTED,
    MCP_CATALOG_CHANGED,
    MCP_CATALOG_FROZEN,
    MCP_EVENT_RECEIVED,
    EnvironmentEvent,
    ToolCall,
    ToolOutput,
    ToolStatus,
    WorldCommit,
    WorldCommitInput,
    WorldFrontier,
    mcp_scope,
)
from src.mcp import (
    McpAppSpec,
    McpAppState,
    McpCallResult,
    McpInboundEvent,
    McpRemoteTool,
    McpStartupError,
    McpToolsPage,
    McpTransport,
    prepare_mcp,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from src.mcp.client import InboundEventHandler

_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class _Call:
    name: str
    arguments: Mapping[str, Any]
    timeout_seconds: float


class FakeClient:
    def __init__(
        self,
        package: str,
        pages: Mapping[str | None, McpToolsPage],
        close_order: list[str],
        *,
        protocol_version: str = "2026-07-28",
    ) -> None:
        self.package = package
        self.pages = dict(pages)
        self.close_order = close_order
        self._protocol_version = protocol_version
        self._connected = True
        self.list_cursors: list[str | None] = []
        self.calls: list[_Call] = []
        self.call_results: dict[str, McpCallResult | Exception] = {}
        self.catalog_changed: Callable[[], Awaitable[None]] | None = None
        self.disconnected: Callable[[str], Awaitable[None]] | None = None
        self.event_handler: InboundEventHandler | None = None
        self.events_active = False
        self.activation_count = 0
        self.deactivation_count = 0
        self.lifecycle: list[str] = []

    @property
    def protocol_version(self) -> str:
        return self._protocol_version

    @property
    def connected(self) -> bool:
        return self._connected

    async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage:
        self.lifecycle.append(f"list:{cursor}")
        self.list_cursors.append(cursor)
        return self.pages[cursor]

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        timeout_seconds: float,
    ) -> McpCallResult:
        self.calls.append(_Call(name, dict(arguments), timeout_seconds))
        result = self.call_results[name]
        if isinstance(result, Exception):
            raise result
        return result

    async def bind_observers(
        self,
        *,
        catalog_changed: Callable[[], Awaitable[None]],
        disconnected: Callable[[str], Awaitable[None]],
    ) -> None:
        self.lifecycle.append("bind")
        self.catalog_changed = catalog_changed
        self.disconnected = disconnected

    def activate_events(self) -> None:
        self.lifecycle.append("activate")
        self.activation_count += 1
        self.events_active = True

    def deactivate_events(self) -> None:
        self.lifecycle.append("deactivate")
        self.deactivation_count += 1
        self.events_active = False

    async def emit_catalog_changed(self) -> None:
        assert self.catalog_changed is not None
        await self.catalog_changed()

    async def emit_disconnected(self, detail: str) -> None:
        self._connected = False
        assert self.disconnected is not None
        await self.disconnected(detail)

    async def emit_event(self, event: McpInboundEvent) -> bool:
        if not self.events_active:
            return False
        assert self.event_handler is not None
        await self.event_handler(event)
        return True

    async def close(self) -> None:
        self.lifecycle.append("close")
        self._connected = False
        self.close_order.append(self.package)


class FakeFactory:
    def __init__(self, clients: Mapping[str, FakeClient]) -> None:
        self.clients = dict(clients)
        self.opened: list[str] = []
        self.event_handlers: dict[str, InboundEventHandler] = {}

    async def open(self, spec: McpAppSpec, event_handler: InboundEventHandler) -> FakeClient:
        self.opened.append(spec.package)
        self.event_handlers[spec.package] = event_handler
        client = self.clients[spec.package]
        client.event_handler = event_handler
        return client


class FakeWorld:
    def __init__(self) -> None:
        self.commits: list[WorldCommitInput] = []
        self.append_attempts = 0
        self.append_event_calls = 0

    async def append_event(self, event: EnvironmentEvent) -> WorldCommit:
        self.append_event_calls += 1
        raise AssertionError(f"MCP 不应通过 append_event 写入：{event.event_id}")

    async def append_commit(
        self,
        *,
        commit_id: str,
        kind: str,
        source: str,
        summary: str,
        scopes: frozenset[str],
        based_on: WorldFrontier,
        data: Mapping[str, Any],
        occurred_at: datetime | None = None,
    ) -> WorldCommit:
        self.append_attempts += 1
        item = WorldCommitInput(commit_id, kind, source, summary, scopes, based_on, data, occurred_at)
        self.commits.append(item)
        sequence = len(self.commits)
        return WorldCommit(
            item.commit_id,
            item.kind,
            item.source,
            item.summary,
            item.occurred_at or datetime.now(UTC),
            {scope: sequence for scope in item.scopes},
            item.based_on,
            item.data,
        )

    async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]:
        raise AssertionError(f"MCP 不应批量写入世界：{len(inputs)}")


def _spec(package: str, *, enabled: bool = True, timeout_seconds: float = _TIMEOUT_SECONDS) -> McpAppSpec:
    return McpAppSpec(
        package=package,
        enabled=enabled,
        transport=McpTransport.STDIO,
        timeout_seconds=timeout_seconds,
        terminal_logs=False,
        command=("fake-mcp",),
        working_dir=Path("/tmp"),
    )


def _tool(name: str, *, schema_type: str = "object") -> McpRemoteTool:
    return McpRemoteTool(name, f"{name} 工具", {"type": schema_type, "properties": {}})


def _client(
    package: str,
    close_order: list[str],
    *tools: McpRemoteTool,
    next_cursor: str | None = None,
) -> FakeClient:
    return FakeClient(package, {None: McpToolsPage(tuple(tools), next_cursor)}, close_order)


def test_prepare_mcp_reads_every_page_then_publishes_one_frozen_catalog() -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        package = "org.example.clock"
        client = FakeClient(
            package,
            {
                None: McpToolsPage((_tool("zeta"),), "page-2"),
                "page-2": McpToolsPage((_tool("alpha"),)),
            },
            close_order,
        )
        factory = FakeFactory({package: client})
        world = FakeWorld()

        runtime = await prepare_mcp((_spec(package),), platform_enabled=True, world=world, factory=factory)
        try:
            assert factory.opened == [package]
            assert client.list_cursors == [None, "page-2"]
            assert client.lifecycle[:3] == ["bind", "list:None", "list:page-2"]
            assert client.events_active is False
            assert tuple(tool.definition.name for tool in runtime.tools) == (
                "aur.mcp.org.example.clock.alpha",
                "aur.mcp.org.example.clock.zeta",
            )
            snapshot = runtime.snapshot()
            assert snapshot.tool_ids == tuple(tool.definition.name for tool in runtime.tools)
            assert snapshot.restart_required is False
            assert snapshot.apps[0].state is McpAppState.READY
            assert snapshot.apps[0].negotiated_version == "2026-07-28"
            assert snapshot.apps[0].tool_ids == (
                "aur.mcp.org.example.clock.zeta",
                "aur.mcp.org.example.clock.alpha",
            )
            frozen = [commit for commit in world.commits if commit.kind == MCP_CATALOG_FROZEN]
            assert len(frozen) == 1
            assert frozen[0].data == {
                "tool_ids": list(snapshot.apps[0].tool_ids),
                "tool_count": 2,
            }
            assert client.catalog_changed is not None and client.disconnected is not None
            await runtime.activate()
            assert client.events_active is True
            assert client.activation_count == 1
        finally:
            await runtime.close()
        assert close_order == [package]
        assert client.events_active is False

    asyncio.run(scenario())


@pytest.mark.parametrize(("stall", "phase"), (("open", "connect"), ("pagination", "tools/list")))
def test_single_app_startup_deadline_bounds_open_and_the_whole_pagination(stall: str, phase: str) -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        package = "org.example.deadline"

        class StallingClient(FakeClient):
            async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage:
                if stall == "pagination" and cursor == "next":
                    self.lifecycle.append("list:next")
                    self.list_cursors.append(cursor)
                    await asyncio.Event().wait()
                    raise AssertionError("不可达")
                return await super().list_tools(cursor=cursor)

        class StallingFactory(FakeFactory):
            async def open(self, spec: McpAppSpec, event_handler: InboundEventHandler) -> FakeClient:
                if stall == "open":
                    self.opened.append(spec.package)
                    await asyncio.Event().wait()
                    raise AssertionError("不可达")
                return await super().open(spec, event_handler)

        client = StallingClient(
            package,
            {None: McpToolsPage((), "next")},
            close_order,
        )
        factory = StallingFactory({package: client})

        with pytest.raises(McpStartupError) as captured:
            await prepare_mcp(
                (_spec(package, timeout_seconds=0.01),),
                platform_enabled=True,
                world=FakeWorld(),
                factory=factory,
            )

        assert captured.value.phase == phase
        assert "TimeoutError" in captured.value.detail
        assert factory.opened == [package]
        if stall == "pagination":
            assert client.lifecycle[:3] == ["bind", "list:None", "list:next"]
            assert close_order == [package]
        else:
            assert close_order == []

    asyncio.run(scenario())


def test_startup_failure_closes_opened_clients_in_reverse_without_freezing_partial_catalog() -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        first_package = "org.example.first"
        second_package = "org.example.second"
        first = _client(first_package, close_order, _tool("valid"))
        second = _client(second_package, close_order, _tool("invalid", schema_type="array"))
        factory = FakeFactory({first_package: first, second_package: second})
        world = FakeWorld()

        with pytest.raises(McpStartupError, match="input schema 必须是 object") as captured:
            await prepare_mcp(
                (_spec(first_package), _spec(second_package)),
                platform_enabled=True,
                world=world,
                factory=factory,
            )

        assert captured.value.package == second_package
        assert captured.value.phase == "tools/list"
        assert close_order == [second_package, first_package]
        assert first.catalog_changed is not None and second.catalog_changed is not None
        assert first.disconnected is not None and second.disconnected is not None
        assert first.events_active is second.events_active is False
        assert all(commit.kind != MCP_CATALOG_FROZEN for commit in world.commits)

    asyncio.run(scenario())


def test_discovery_rejects_duplicate_raw_tool_names() -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        package = "org.example.duplicate"
        client = FakeClient(
            package,
            {
                None: McpToolsPage((_tool("same"),), "next"),
                "next": McpToolsPage((_tool("same"),)),
            },
            close_order,
        )

        with pytest.raises(McpStartupError, match="工具名称重复"):
            await prepare_mcp(
                (_spec(package),),
                platform_enabled=True,
                world=FakeWorld(),
                factory=FakeFactory({package: client}),
            )
        assert close_order == [package]

    asyncio.run(scenario())


def test_discovery_rejects_cursor_cycles() -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        package = "org.example.cursor"
        client = FakeClient(
            package,
            {
                None: McpToolsPage((), "again"),
                "again": McpToolsPage((), "again"),
            },
            close_order,
        )

        with pytest.raises(McpStartupError, match="循环 cursor"):
            await prepare_mcp(
                (_spec(package),),
                platform_enabled=True,
                world=FakeWorld(),
                factory=FakeFactory({package: client}),
            )
        assert client.list_cursors == [None, "again"]

    asyncio.run(scenario())


def test_prepare_mcp_rejects_duplicate_package_ids_before_opening_connections() -> None:
    package = "org.example.same"
    close_order: list[str] = []
    client = _client(package, close_order)
    factory = FakeFactory({package: client})

    with pytest.raises(ValueError, match="package 不能重复"):
        asyncio.run(
            prepare_mcp(
                (_spec(package), _spec(package)),
                platform_enabled=True,
                world=FakeWorld(),
                factory=factory,
            )
        )
    assert factory.opened == []


@pytest.mark.parametrize("transition", ("catalog", "disconnect"))
def test_prepared_catalog_change_or_disconnect_prevents_activation(transition: str) -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        package = "org.example.prepared"
        client = _client(package, close_order, _tool("before"))
        runtime = await prepare_mcp(
            (_spec(package),),
            platform_enabled=True,
            world=FakeWorld(),
            factory=FakeFactory({package: client}),
        )
        try:
            assert client.events_active is False
            if transition == "catalog":
                await client.emit_catalog_changed()
            else:
                await client.emit_disconnected("transport lost before activate")

            with pytest.raises(McpStartupError) as captured:
                await runtime.activate()

            assert captured.value.phase == "activate"
            assert client.activation_count == 0
            assert client.events_active is False
            if transition == "catalog":
                assert "目录发生变化" in captured.value.detail
            else:
                assert "transport lost before activate" in captured.value.detail
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_catalog_change_only_marks_restart_and_keeps_the_frozen_tools() -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        package = "org.example.catalog"
        client = _client(package, close_order, _tool("before"))
        world = FakeWorld()
        runtime = await prepare_mcp(
            (_spec(package),),
            platform_enabled=True,
            world=world,
            factory=FakeFactory({package: client}),
        )
        try:
            await runtime.activate()
            frozen_tools = runtime.tools
            list_cursors = tuple(client.list_cursors)
            replacement_pages: dict[str | None, McpToolsPage] = {None: McpToolsPage((_tool("after"),))}
            client.pages = replacement_pages

            await client.emit_catalog_changed()
            await client.emit_catalog_changed()

            snapshot = runtime.snapshot()
            assert runtime.tools is frozen_tools
            assert snapshot.tool_ids == ("aur.mcp.org.example.catalog.before",)
            assert snapshot.apps[0].state is McpAppState.READY
            assert snapshot.apps[0].restart_required is True
            assert snapshot.restart_required is True
            assert tuple(client.list_cursors) == list_cursors
            changed = [commit for commit in world.commits if commit.kind == MCP_CATALOG_CHANGED]
            assert len(changed) == 1
            assert changed[0].data == {
                "restart_required": True,
                "frozen_tool_ids": ["aur.mcp.org.example.catalog.before"],
            }
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_disconnect_marks_app_unavailable_and_prevents_later_tool_calls() -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        package = "org.example.offline"
        client = _client(package, close_order, _tool("ping"))
        client.call_results["ping"] = McpCallResult(False, None, ())
        world = FakeWorld()
        runtime = await prepare_mcp(
            (_spec(package),),
            platform_enabled=True,
            world=world,
            factory=FakeFactory({package: client}),
        )
        try:
            await runtime.activate()
            await client.emit_disconnected("transport lost")
            result = await runtime.tools[0].execute(
                ToolCall("call-after-disconnect", "aur.mcp.org.example.offline.ping", {})
            )

            app = runtime.app(package)
            assert app is not None
            assert isinstance(result, ToolOutput)
            assert app.state is McpAppState.UNAVAILABLE
            assert app.last_error == "transport lost"
            assert app.restart_required is True
            assert result.status is ToolStatus.FAILED
            assert "未连接" in result.content
            assert client.calls == []
            assert any(commit.kind == MCP_APP_DISCONNECTED for commit in world.commits)
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_inbound_event_gate_drops_pre_activation_and_only_appends_world_after_activation() -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        package = "org.example.events"
        client = _client(package, close_order, _tool("ping"))
        factory = FakeFactory({package: client})
        world = FakeWorld()
        runtime = await prepare_mcp((_spec(package),), platform_enabled=True, world=world, factory=factory)
        try:
            snapshot_before = runtime.snapshot()
            tools_before = runtime.tools
            commits_before = len(world.commits)
            occurred_at = datetime(2026, 8, 24, 10, 30, tzinfo=timezone(timedelta(hours=8)))
            event = McpInboundEvent(
                "message:42",
                "qq:group:100",
                "qq.message",
                occurred_at,
                "收到一条群消息",
                {"message": {"id": 42, "text": "你好"}},
            )

            assert await client.emit_event(event) is False
            assert len(world.commits) == commits_before
            await runtime.activate()
            assert await client.emit_event(event) is True

            assert len(world.commits) == commits_before + 1
            commit = world.commits[-1]
            assert commit.kind == MCP_EVENT_RECEIVED
            assert commit.source == f"mcp:{package}"
            assert commit.summary == event.summary
            assert commit.scopes == frozenset({"qq:group:100", mcp_scope(package)})
            assert commit.occurred_at == occurred_at.astimezone(UTC)
            assert commit.data == {
                "event_id": "message:42",
                "event_kind": "qq.message",
                "data": {"message": {"id": 42, "text": "你好"}},
            }
            assert world.append_event_calls == 0
            assert runtime.tools is tools_before
            assert runtime.snapshot() == snapshot_before
            assert client.calls == []
        finally:
            await runtime.close()

    asyncio.run(scenario())


def test_inbound_event_rejects_invalid_identity_scope_kind_time_and_data_before_world_write() -> None:
    async def scenario() -> None:
        close_order: list[str] = []
        package = "org.example.validation"
        client = _client(package, close_order)
        factory = FakeFactory({package: client})
        world = FakeWorld()
        runtime = await prepare_mcp((_spec(package),), platform_enabled=True, world=world, factory=factory)
        aware = datetime(2026, 8, 24, tzinfo=UTC)
        valid = McpInboundEvent("event-1", "qq:group:1", "qq.message", aware, "有效事件", {})
        invalid_events = (
            McpInboundEvent("contains space", valid.scope, valid.kind, aware, valid.summary, {}),
            McpInboundEvent(valid.event_id, "scope\nline", valid.kind, aware, valid.summary, {}),
            McpInboundEvent(valid.event_id, "s" * 257, valid.kind, aware, valid.summary, {}),
            McpInboundEvent(valid.event_id, valid.scope, "engine.forged", aware, valid.summary, {}),
            McpInboundEvent(valid.event_id, valid.scope, "", aware, valid.summary, {}),
            McpInboundEvent(valid.event_id, valid.scope, "qq.\nmessage", aware, valid.summary, {}),
            McpInboundEvent(valid.event_id, valid.scope, valid.kind, aware, "  ", {}),
            McpInboundEvent(
                valid.event_id,
                valid.scope,
                valid.kind,
                datetime(2026, 8, 24),  # noqa: DTZ001 - deliberately exercises rejection of a naive timestamp
                valid.summary,
                {},
            ),
            McpInboundEvent(valid.event_id, valid.scope, valid.kind, aware, valid.summary, {"bad": object()}),
        )
        try:
            await runtime.activate()
            for event in invalid_events:
                commits_before = len(world.commits)
                attempts_before = world.append_attempts
                with pytest.raises((TypeError, ValueError)):
                    await client.emit_event(event)
                assert len(world.commits) == commits_before
                assert world.append_attempts == attempts_before
        finally:
            await runtime.close()

    asyncio.run(scenario())
