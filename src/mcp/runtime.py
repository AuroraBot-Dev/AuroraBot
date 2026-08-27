"""MCP 启动发现、冻结目录、状态观察与逆序关闭。"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.contracts import (
    MCP_APP_DISCONNECTED,
    MCP_APP_FAILED,
    MCP_APP_READY,
    MCP_APP_STARTING,
    MCP_CATALOG_CHANGED,
    MCP_CATALOG_FROZEN,
    MCP_EVENT_RECEIVED,
    WorldFrontier,
    mcp_scope,
)
from src.mcp.client import McpClientFactory, McpClientPort, SdkMcpClientFactory
from src.mcp.models import (
    McpAppSnapshot,
    McpAppSpec,
    McpAppState,
    McpInboundEvent,
    McpRuntimeSnapshot,
    McpStartupError,
)
from src.mcp.scopes import validate_mcp_scope
from src.mcp.tool import McpTool, bind_mcp_tool
from src.utils import get_logger

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.contracts import Tool, WorldWriter
    from src.mcp.tool import McpToolBinding

_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")
_RESERVED_EVENT_PREFIXES = ("engine.", "tool.", "output.", "cadence.", "ops.", "mcp.")
_CONTROL_CHARACTER_LIMIT = 32
_MAX_TOOL_PAGES = 1024
_MAX_TOOLS = 10_000


class _RuntimePhase(StrEnum):
    PREPARING = "preparing"
    PREPARED = "prepared"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass(slots=True)
class _AppRecord:
    spec: McpAppSpec
    active: bool
    state: McpAppState
    client: McpClientPort | None = None
    negotiated_version: str | None = None
    tool_ids: tuple[str, ...] = ()
    last_error: str | None = None
    restart_required: bool = False
    change_sequence: int = 0
    startup_catalog_changed: bool = False
    startup_disconnect: str | None = None

    def snapshot(self) -> McpAppSnapshot:
        return McpAppSnapshot(
            self.spec.package,
            self.spec.enabled,
            self.active,
            self.spec.transport,
            self.state,
            self.negotiated_version,
            self.tool_ids,
            self.last_error,
            self.restart_required,
        )


class McpRuntime:
    """持有活连接与冻结 Tool 集合；状态可变但目录身份不可变。"""

    def __init__(
        self,
        platform_enabled: bool,
        records: tuple[_AppRecord, ...],
        tools: tuple[Tool, ...],
        world: WorldWriter | None,
        startup_id: str,
    ) -> None:
        self._platform_enabled = platform_enabled
        self._records = records
        self._by_package = {record.spec.package: record for record in records}
        self._tools = tools
        self._world = world
        self._startup_id = startup_id
        self._phase = _RuntimePhase.PREPARING
        self._close_lock = asyncio.Lock()
        self._status_lock = asyncio.Lock()

    @classmethod
    def disabled(cls, specs: Iterable[McpAppSpec], *, platform_enabled: bool) -> McpRuntime:
        """为没有任何生效 App 的同步组合构造只读状态。"""
        records = tuple(_AppRecord(spec, platform_enabled and spec.enabled, McpAppState.DISABLED) for spec in specs)
        if any(record.active for record in records):
            raise ValueError("存在已启用 MCP App；必须先经过异步连接与完整工具发现")
        runtime = cls(platform_enabled, records, (), None, uuid4().hex)
        runtime._phase = _RuntimePhase.RUNNING
        return runtime

    @property
    def tools(self) -> tuple[Tool, ...]:
        return self._tools

    def snapshot(self) -> McpRuntimeSnapshot:
        apps = tuple(record.snapshot() for record in self._records)
        return McpRuntimeSnapshot(
            self._platform_enabled,
            tuple(tool.definition.name for tool in self._tools),
            apps,
            any(app.restart_required for app in apps),
        )

    def app(self, package: str) -> McpAppSnapshot | None:
        record = self._by_package.get(package)
        return record.snapshot() if record is not None else None

    async def activate(self) -> None:
        """在最终 ToolRegistry/runner 组合成功后原子放行业务事件。"""
        async with self._status_lock:
            if self._phase is _RuntimePhase.RUNNING:
                return
            if self._phase is not _RuntimePhase.PREPARED:
                raise RuntimeError(f"MCP runtime 当前不能激活：{self._phase}")
            invalid = self._startup_invalid_record()
            if invalid is not None:
                raise McpStartupError(invalid.spec.package, "activate", self._startup_invalid_detail(invalid))
            self._phase = _RuntimePhase.RUNNING
            for record in self._records:
                if record.client is not None:
                    record.client.activate_events()
            _logger.info("MCP runtime 已激活 app_count={} tool_count={}", len(self._records), len(self._tools))

    async def close(self) -> None:
        """逆序且幂等地关闭 SDK Client 和 stdio/HTTP 资源。"""
        async with self._close_lock:
            if self._phase is _RuntimePhase.CLOSED:
                return
            async with self._status_lock:
                self._phase = _RuntimePhase.CLOSING
                for record in self._records:
                    if record.client is not None:
                        record.client.deactivate_events()
            for record in reversed(self._records):
                if record.client is None:
                    continue
                try:
                    await record.client.close()
                except Exception as error:  # noqa: BLE001 - one cleanup failure must not skip remaining clients
                    _logger.error(
                        "MCP App 关闭失败 package={} error_type={}",
                        record.spec.package,
                        type(error).__name__,
                    )
                    record.last_error = f"关闭失败：{type(error).__name__}: {error}"
                finally:
                    record.state = McpAppState.CLOSED
            async with self._status_lock:
                self._phase = _RuntimePhase.CLOSED
            _logger.info("MCP runtime 已关闭")

    async def _catalog_changed(self, package: str) -> None:
        record = self._by_package[package]
        async with self._status_lock:
            if self._phase in {_RuntimePhase.CLOSING, _RuntimePhase.CLOSED}:
                return
            if self._phase in {_RuntimePhase.PREPARING, _RuntimePhase.PREPARED}:
                record.startup_catalog_changed = True
                record.change_sequence += 1
                return
            if record.restart_required:
                return
            record.restart_required = True
            record.change_sequence += 1
            sequence = record.change_sequence
            _logger.warning("MCP 工具目录变化 package={} restart_required=true", package)
            await self._append_status(
                record,
                MCP_CATALOG_CHANGED,
                f"MCP 工具目录已变化，需要重启：{package}",
                f"catalog-changed:{sequence}",
                {"restart_required": True, "frozen_tool_ids": list(record.tool_ids)},
            )

    async def _disconnected(self, package: str, detail: str) -> None:
        record = self._by_package[package]
        async with self._status_lock:
            if self._phase in {_RuntimePhase.CLOSING, _RuntimePhase.CLOSED}:
                return
            if self._phase in {_RuntimePhase.PREPARING, _RuntimePhase.PREPARED}:
                record.state = McpAppState.UNAVAILABLE
                record.last_error = detail
                record.startup_disconnect = detail
                record.change_sequence += 1
                return
            if record.state is McpAppState.UNAVAILABLE:
                return
            record.state = McpAppState.UNAVAILABLE
            record.last_error = detail
            record.restart_required = True
            record.change_sequence += 1
            sequence = record.change_sequence
            _logger.warning("MCP App 连接中断 package={}", package)
            await self._append_status(
                record,
                MCP_APP_DISCONNECTED,
                f"MCP App 连接已中断：{package}",
                f"disconnected:{sequence}",
                {"error": detail, "restart_required": True},
            )

    async def _freeze(self, tools_by_id: dict[str, Tool]) -> None:
        async with self._status_lock:
            invalid = self._startup_invalid_record()
            if invalid is not None:
                raise McpStartupError(invalid.spec.package, "catalog/freeze", self._startup_invalid_detail(invalid))
            self._tools = tuple(tools_by_id[name] for name in sorted(tools_by_id))
            self._phase = _RuntimePhase.PREPARED
            _logger.info("MCP 工具目录冻结 tool_count={}", len(self._tools))

    def _startup_invalid_record(self) -> _AppRecord | None:
        return next(
            (
                record
                for record in self._records
                if record.active
                and (
                    record.startup_catalog_changed
                    or record.startup_disconnect is not None
                    or record.client is None
                    or not record.client.connected
                )
            ),
            None,
        )

    @staticmethod
    def _startup_invalid_detail(record: _AppRecord) -> str:
        if record.startup_catalog_changed:
            return "启动期间工具目录发生变化"
        return record.startup_disconnect or "启动期间 MCP 连接已中断"

    async def _append_status(
        self,
        record: _AppRecord,
        kind: str,
        summary: str,
        suffix: str,
        data: dict[str, Any],
    ) -> None:
        if self._world is None:
            return
        await self._world.append_commit(
            commit_id=f"mcp:{self._startup_id}:{record.spec.package}:{suffix}",
            kind=kind,
            source=f"mcp:{record.spec.package}",
            summary=summary,
            scopes=frozenset({mcp_scope(record.spec.package)}),
            based_on=WorldFrontier(),
            data=data,
        )


async def prepare_mcp(
    specs: Iterable[McpAppSpec],
    *,
    platform_enabled: bool,
    world: WorldWriter,
    factory: McpClientFactory | None = None,
) -> McpRuntime:
    """连接全部生效 App，完整分页发现后一次性生成冻结目录。"""
    records = tuple(_AppRecord(spec, platform_enabled and spec.enabled, McpAppState.DISABLED) for spec in specs)
    _reject_duplicate_packages(records)
    runtime = McpRuntime(platform_enabled, records, (), world, uuid4().hex)
    _logger.info("MCP 准备开始 enabled={} app_count={}", platform_enabled, len(records))
    client_factory = factory or SdkMcpClientFactory()
    tools_by_id: dict[str, Tool] = {}
    try:
        for record in records:
            if not record.active:
                continue
            await _prepare_app(runtime, record, tools_by_id, client_factory, world)
        await runtime._freeze(tools_by_id)
        for record in records:
            if record.state is McpAppState.READY:
                await runtime._append_status(
                    record,
                    MCP_CATALOG_FROZEN,
                    f"MCP 工具目录已冻结：{record.spec.package}",
                    "catalog-frozen",
                    {"tool_ids": list(record.tool_ids), "tool_count": len(record.tool_ids)},
                )
        return runtime
    except BaseException:
        await runtime.close()
        raise


async def _prepare_app(
    runtime: McpRuntime,
    record: _AppRecord,
    tools_by_id: dict[str, Tool],
    factory: McpClientFactory,
    world: WorldWriter,
) -> None:
    package = record.spec.package
    record.state = McpAppState.STARTING
    _logger.info("MCP App 启动 package={} transport={}", package, record.spec.transport.value)
    await runtime._append_status(record, MCP_APP_STARTING, f"正在连接 MCP App：{package}", "starting", {})
    phase = "connect"
    try:
        async with asyncio.timeout(record.spec.timeout_seconds):
            client = await factory.open(
                record.spec,
                lambda event: _append_inbound_event(world, package, event),
            )
            record.client = client
            record.negotiated_version = client.protocol_version
            phase = "catalog/listen"
            await client.bind_observers(
                catalog_changed=lambda: runtime._catalog_changed(package),
                disconnected=lambda detail: runtime._disconnected(package, detail),
            )
            phase = "tools/list"
            bindings = await _discover_bindings(record)
            async with runtime._status_lock:
                if record.startup_catalog_changed:
                    raise RuntimeError("启动期间工具目录发生变化")
                if record.startup_disconnect is not None or not client.connected:
                    raise RuntimeError(record.startup_disconnect or "启动期间 MCP 连接已中断")
            for binding in bindings:
                tool_id = binding.definition.name
                if tool_id in tools_by_id:
                    raise ValueError(f"MCP Tool 重复注册：{tool_id}")
                tools_by_id[tool_id] = McpTool(binding, client, record.spec.timeout_seconds)
            record.tool_ids = tuple(binding.definition.name for binding in bindings)
            record.state = McpAppState.READY
            _logger.info(
                "MCP App 就绪 package={} protocol={} tool_count={}",
                package,
                client.protocol_version,
                len(bindings),
            )
        await runtime._append_status(
            record,
            MCP_APP_READY,
            f"MCP App 已就绪：{package}",
            "ready",
            {"protocol_version": client.protocol_version, "tool_count": len(bindings)},
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        _logger.error("MCP App 启动失败 package={} phase={} error_type={}", package, phase, type(error).__name__)
        record.state = McpAppState.UNAVAILABLE
        record.last_error = f"{type(error).__name__}: {error}"
        with suppress(Exception):
            await runtime._append_status(
                record,
                MCP_APP_FAILED,
                f"MCP App 启动失败：{package}",
                "failed",
                {"phase": phase, "error": record.last_error},
            )
        raise McpStartupError(package, phase, record.last_error) from error


async def _discover_bindings(record: _AppRecord) -> tuple[McpToolBinding, ...]:
    assert record.client is not None
    cursor: str | None = None
    visited: set[str] = set()
    bindings: list[McpToolBinding] = []
    raw_names: set[str] = set()
    page_count = 0
    while True:
        page_count += 1
        if page_count > _MAX_TOOL_PAGES:
            raise ValueError(f"MCP tools/list 页面过多：{record.spec.package}")
        page = await record.client.list_tools(cursor=cursor)
        for remote in page.tools:
            if remote.name in raw_names:
                raise ValueError(f"MCP App 工具名称重复：{record.spec.package}/{remote.name}")
            raw_names.add(remote.name)
            bindings.append(bind_mcp_tool(record.spec.package, remote))
            if len(bindings) > _MAX_TOOLS:
                raise ValueError(f"MCP App 工具数量过多：{record.spec.package}")
        cursor = page.next_cursor
        if cursor is None:
            break
        if cursor in visited:
            raise ValueError(f"MCP tools/list 返回了循环 cursor：{record.spec.package}")
        visited.add(cursor)
    return tuple(bindings)


async def _append_inbound_event(world: WorldWriter, package: str, event: McpInboundEvent) -> None:
    if _EVENT_ID.fullmatch(event.event_id) is None:
        raise ValueError("MCP 业务事件 event_id 非法")
    try:
        validate_mcp_scope(event.scope)
    except ValueError as error:
        raise ValueError("MCP 业务事件 scope 非法") from error
    if not event.kind.strip() or any(ord(char) < _CONTROL_CHARACTER_LIMIT for char in event.kind):
        raise ValueError("MCP 业务事件 kind 非法")
    if any(event.kind.startswith(prefix) for prefix in _RESERVED_EVENT_PREFIXES):
        raise ValueError(f"MCP 业务事件不能伪造保留 kind：{event.kind}")
    if not event.summary.strip():
        raise ValueError("MCP 业务事件 summary 不能为空")
    if event.occurred_at.tzinfo is None:
        raise ValueError("MCP 业务事件 occurred_at 必须包含时区")
    json.dumps(dict(event.data), ensure_ascii=False)
    await world.append_commit(
        commit_id=f"mcp:{package}:event:{event.event_id}",
        kind=MCP_EVENT_RECEIVED,
        source=f"mcp:{package}",
        summary=event.summary,
        scopes=frozenset({event.scope, mcp_scope(package)}),
        based_on=WorldFrontier(),
        data={"event_id": event.event_id, "event_kind": event.kind, "data": dict(event.data)},
        occurred_at=event.occurred_at.astimezone(UTC),
    )
    _logger.debug("MCP 业务事件已接收 package={} event_id={} kind={}", package, event.event_id, event.kind)


def _reject_duplicate_packages(records: tuple[_AppRecord, ...]) -> None:
    packages = [record.spec.package for record in records]
    if len(packages) != len(set(packages)):
        raise ValueError("MCP App package 不能重复")


__all__ = ["McpRuntime", "prepare_mcp"]
