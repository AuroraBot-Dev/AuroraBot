"""该能力测试共用的离线替身与场景构造。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aurora_bot.contracts import (
    EnvironmentEvent,
    WorldCommit,
    WorldCommitInput,
    WorldFrontier,
)
from aurora_bot.mcp import (
    McpAppSpec,
    McpCallResult,
    McpInboundEvent,
    McpRemoteTool,
    McpToolsPage,
    McpTransport,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from aurora_bot.mcp.client import InboundEventHandler


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
