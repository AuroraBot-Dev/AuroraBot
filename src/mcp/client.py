"""官方 MCP Python SDK 2.x 的窄客户端适配。"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

import httpx2

from mcp.client.client import Client
from mcp.client.extension import ClientExtension
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.client.subscriptions import ToolsListChanged
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CONNECTION_CLOSED,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    REQUEST_TIMEOUT,
    CallToolResult,
    InputRequiredResult,
    LoggingMessageNotificationParams,
    TextContent,
    ToolListChangedNotification,
)
from src.mcp.events import (
    WORLD_EVENT_NOTIFICATION,
    WORLD_EVENTS_EXTENSION,
    InboundEventGate,
    InboundEventHandler,
    WorldEventParams,
    WorldEventsExtension,
    inbound_event,
)
from src.mcp.models import (
    McpAppSpec,
    McpCallRejectedError,
    McpCallResult,
    McpCallUnknownError,
    McpContentBlock,
    McpEventMode,
    McpRemoteTool,
    McpToolsPage,
    McpTransport,
)
from src.utils import get_logger

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import TextIO

    from mcp.client._transport import Transport
    from mcp.client.session import LoggingFnT

TOOL_CONTRACT_EXTENSION = "org.aurorabot/tool-contract"
_MODERN_PROTOCOL = "2026-07-28"

type CatalogChangedHandler = Callable[[], Awaitable[None]]
type DisconnectedHandler = Callable[[str], Awaitable[None]]


class McpClientPort(Protocol):
    """MCP runtime 使用的可替换客户端边界。"""

    @property
    def protocol_version(self) -> str: ...

    @property
    def connected(self) -> bool: ...

    async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage: ...

    async def call_tool(self, name: str, arguments: Mapping[str, Any], timeout_seconds: float) -> McpCallResult: ...

    async def bind_observers(
        self,
        *,
        catalog_changed: CatalogChangedHandler,
        disconnected: DisconnectedHandler,
    ) -> None: ...

    def activate_events(self) -> None: ...

    def deactivate_events(self) -> None: ...

    async def close(self) -> None: ...


class McpClientFactory(Protocol):
    """连接一个 App；实现负责协议协商与底层资源回收。"""

    async def open(self, spec: McpAppSpec, event_handler: InboundEventHandler) -> McpClientPort: ...


class _ToolContractExtension(ClientExtension):
    identifier = TOOL_CONTRACT_EXTENSION

    def settings(self) -> dict[str, Any]:
        return {"version": 1}


@dataclass(slots=True)
class _Callbacks:
    catalog_changed: CatalogChangedHandler | None = None
    disconnected: DisconnectedHandler | None = None
    pending_catalog: int = 0
    pending_disconnect: str | None = None

    async def emit_catalog(self) -> None:
        if self.catalog_changed is None:
            self.pending_catalog += 1
        else:
            await self.catalog_changed()

    async def emit_disconnect(self, detail: str) -> None:
        if self.disconnected is None:
            self.pending_disconnect = detail
        else:
            await self.disconnected(detail)


class SdkMcpClient:
    """一个已经进入 context、可由 runtime 幂等关闭的 SDK v2 Client。"""

    def __init__(
        self,
        client: Client,
        resources: AsyncExitStack,
        callbacks: _Callbacks,
        event_gate: InboundEventGate,
        *,
        tool_contract: bool,
    ) -> None:
        self._client = client
        self._resources = resources
        self._callbacks = callbacks
        self._event_gate = event_gate
        self._tool_contract = tool_contract
        self._connected = True
        self._closing = False
        self._closed = False
        self._watch_task: asyncio.Task[None] | None = None
        self._watch_ready: asyncio.Future[None] | None = None
        self._close_lock = asyncio.Lock()
        self._disconnected_observer: DisconnectedHandler | None = None
        self._disconnect_detail: str | None = None
        self._disconnect_delivered = False
        self._observers_bound = False

    @property
    def protocol_version(self) -> str:
        return self._client.protocol_version

    @property
    def connected(self) -> bool:
        return self._connected

    async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage:
        _logger.debug("MCP tools/list 开始 cursor_present={}", cursor is not None)
        result = await self._client.list_tools(cursor=cursor, cache_mode="bypass")
        page = McpToolsPage(
            tuple(
                McpRemoteTool(
                    tool.name,
                    tool.description,
                    tool.input_schema,
                    _tool_contract_meta(tool.meta) if self._tool_contract else None,
                )
                for tool in result.tools
            ),
            result.next_cursor,
        )
        _logger.debug("MCP tools/list 完成 tool_count={} has_next={}", len(page.tools), page.next_cursor is not None)
        return page

    async def call_tool(self, name: str, arguments: Mapping[str, Any], timeout_seconds: float) -> McpCallResult:
        if not self._connected:
            raise McpCallRejectedError("MCP App 当前未连接，调用未发送")
        _logger.debug("MCP tools/call 开始 tool={}", name)
        try:
            result = await self._client.session.call_tool(
                name,
                dict(arguments),
                read_timeout_seconds=timeout_seconds,
                allow_input_required=True,
            )
        except asyncio.CancelledError:
            raise
        except MCPError as error:
            _logger.warning("MCP tools/call 协议失败 tool={} code={}", name, error.code)
            if error.code == CONNECTION_CLOSED:
                await self._mark_disconnected(str(error))
                raise McpCallUnknownError(f"MCP 连接已中断，调用效果未知：{error}") from error
            if error.code == REQUEST_TIMEOUT:
                raise McpCallUnknownError(f"MCP 调用超时，效果未知：{error}") from error
            if error.code in {INVALID_PARAMS, METHOD_NOT_FOUND}:
                raise McpCallRejectedError(f"MCP Server 明确拒绝调用：{error}") from error
            raise McpCallUnknownError(f"MCP Server 错误无法确认调用效果：{error}") from error
        except Exception as error:
            _logger.error("MCP tools/call 失败 tool={} error_type={}", name, type(error).__name__)
            raise McpCallUnknownError(f"MCP 调用结果无法确认：{type(error).__name__}: {error}") from error
        if isinstance(result, InputRequiredResult):
            raise McpCallUnknownError("MCP Tool 请求 input_required，当前调用效果无法确认")
        if not isinstance(result, CallToolResult):
            raise McpCallUnknownError("MCP Tool 返回了未启用的扩展结果，调用效果无法确认")
        normalized = McpCallResult(
            result.is_error,
            result.structured_content,
            tuple(
                McpContentBlock("text", block.text)
                if isinstance(block, TextContent)
                else McpContentBlock(str(block.type))
                for block in result.content
            ),
            _result_effect_unknown(result, negotiated=self._tool_contract),
        )
        _logger.debug("MCP tools/call 完成 tool={} is_error={}", name, normalized.is_error)
        return normalized

    async def bind_observers(
        self,
        *,
        catalog_changed: CatalogChangedHandler,
        disconnected: DisconnectedHandler,
    ) -> None:
        if self._observers_bound:
            raise RuntimeError("MCP observers 只能绑定一次")
        self._observers_bound = True
        self._callbacks.catalog_changed = catalog_changed
        self._disconnected_observer = disconnected
        if self.protocol_version == _MODERN_PROTOCOL:
            loop = asyncio.get_running_loop()
            self._watch_ready = loop.create_future()
            self._watch_task = asyncio.create_task(self._watch_catalog(), name="aurora-mcp-catalog-watch")
            await self._watch_ready
        pending_catalog = self._callbacks.pending_catalog
        self._callbacks.pending_catalog = 0
        for _ in range(pending_catalog):
            await catalog_changed()
        if self._callbacks.pending_disconnect is not None:
            await self._mark_disconnected(self._callbacks.pending_disconnect)
            self._callbacks.pending_disconnect = None
        await self._deliver_disconnect()

    def activate_events(self) -> None:
        self._event_gate.activate()

    def deactivate_events(self) -> None:
        self._event_gate.deactivate()

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            self.deactivate_events()
            task = self._watch_task
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            try:
                await self._resources.aclose()
            except BaseException:
                self._closing = False
                raise
            self._connected = False
            self._closed = True
            self._closing = False
            _logger.info("MCP SDK client 已关闭")

    async def _watch_catalog(self) -> None:
        assert self._watch_ready is not None
        try:
            async with self._client.listen(tools_list_changed=True) as subscription:
                if subscription.honored.tools_list_changed is not True:
                    raise RuntimeError("MCP Server 未接受 tools_list_changed 订阅")
                self._watch_ready.set_result(None)
                async for event in subscription:
                    if not isinstance(event, ToolsListChanged):
                        raise RuntimeError("MCP tools_list_changed 订阅返回了无关事件")
                    # SDK 会把同一帧同步 tee 给 message_handler；这里只负责持续 drain。
                raise RuntimeError("MCP tools_list_changed 订阅提前结束")
        except asyncio.CancelledError:
            if not self._watch_ready.done():
                self._watch_ready.cancel()
            raise
        except Exception as error:  # noqa: BLE001 - subscription transport faults are an external boundary
            if not self._watch_ready.done():
                self._watch_ready.set_exception(error)
            elif not self._closing:
                await self._mark_disconnected(f"{type(error).__name__}: {error}")

    async def _mark_disconnected(self, detail: str) -> None:
        if self._disconnect_detail is None:
            self._disconnect_detail = detail
        self._connected = False
        await self._deliver_disconnect()

    async def _deliver_disconnect(self) -> None:
        if (
            self._disconnect_detail is not None
            and self._disconnected_observer is not None
            and not self._disconnect_delivered
        ):
            self._disconnect_delivered = True
            await self._disconnected_observer(self._disconnect_detail)


class SdkMcpClientFactory:
    """只使用 SDK v2 公共 API 构造 stdio 或 Streamable HTTP Client。"""

    async def open(self, spec: McpAppSpec, event_handler: InboundEventHandler) -> McpClientPort:
        resources = AsyncExitStack()
        callbacks = _Callbacks()
        gate = InboundEventGate(event_handler)
        _logger.info("MCP SDK client 连接开始 package={} transport={}", spec.package, spec.transport.value)

        async def message_handler(message: object) -> None:
            if isinstance(message, ToolListChangedNotification):
                await callbacks.emit_catalog()
            elif isinstance(message, Exception):
                await callbacks.emit_disconnect(f"{type(message).__name__}: {message}")

        logging_callback = self._logging_callback(spec, gate)
        extensions: list[ClientExtension] = [_ToolContractExtension()]
        if spec.event_mode is McpEventMode.WORLD_EVENTS:
            extensions.append(WorldEventsExtension(gate))
        try:
            target = await self._target(resources, spec)
            client = Client(
                target,
                mode="auto",
                cache=None,
                read_timeout_seconds=spec.timeout_seconds,
                input_required_max_rounds=0,
                message_handler=message_handler,
                logging_callback=logging_callback,
                extensions=tuple(extensions),
            )
            await resources.enter_async_context(client)
            self._validate_event_negotiation(client, spec)
            tool_contract = _has_v1_extension(client, TOOL_CONTRACT_EXTENSION)
        except BaseException:
            gate.deactivate()
            await resources.aclose()
            raise
        wrapper = SdkMcpClient(client, resources, callbacks, gate, tool_contract=tool_contract)
        callbacks.disconnected = wrapper._mark_disconnected
        _logger.info("MCP SDK client 连接完成 package={} protocol={}", spec.package, client.protocol_version)
        return wrapper

    @staticmethod
    async def _target(resources: AsyncExitStack, spec: McpAppSpec) -> Transport:
        if spec.transport is McpTransport.STDIO:
            return SdkMcpClientFactory._stdio_target(spec)
        assert spec.url is not None
        headers = {"Authorization": f"Bearer {spec.auth_token}"} if spec.auth_token is not None else None
        http_client = await resources.enter_async_context(
            httpx2.AsyncClient(headers=headers, follow_redirects=False, timeout=httpx2.Timeout(spec.timeout_seconds))
        )
        return streamable_http_client(spec.url, http_client=http_client)

    @staticmethod
    def _stdio_target(spec: McpAppSpec) -> Transport:
        assert spec.working_dir is not None
        errlog = sys.stderr
        if not spec.terminal_logs:
            errlog = cast("TextIO", subprocess.DEVNULL)
        parameters = StdioServerParameters(
            command=spec.command[0],
            args=list(spec.command[1:]),
            env=dict(spec.environment),
            cwd=spec.working_dir,
        )
        return stdio_client(parameters, errlog=errlog)

    @staticmethod
    def _logging_callback(spec: McpAppSpec, gate: InboundEventGate) -> LoggingFnT | None:
        if spec.event_mode is not McpEventMode.LEGACY_AURORA_EVENT:
            return None

        async def handle(params: LoggingMessageNotificationParams) -> None:
            if params.logger != "aurora/event":
                return
            event = WorldEventParams.model_validate(params.data)
            await gate.deliver(gate.snapshot(), inbound_event(event))

        return cast("LoggingFnT", handle)

    @staticmethod
    def _validate_event_negotiation(client: Client, spec: McpAppSpec) -> None:
        if spec.event_mode is McpEventMode.WORLD_EVENTS and (
            client.protocol_version != _MODERN_PROTOCOL or not _has_v1_extension(client, WORLD_EVENTS_EXTENSION)
        ):
            raise RuntimeError(f"MCP Server 未严格协商事件扩展：{WORLD_EVENTS_EXTENSION}")
        if spec.event_mode is McpEventMode.LEGACY_AURORA_EVENT and client.protocol_version == _MODERN_PROTOCOL:
            raise RuntimeError("legacy_aurora_event 只允许用于握手时代的 MCP Server")


def _has_v1_extension(client: Client, identifier: str) -> bool:
    settings = (client.server_capabilities.extensions or {}).get(identifier)
    return (
        isinstance(settings, Mapping)
        and set(settings) == {"version"}
        and type(settings["version"]) is int
        and settings["version"] == 1
    )


def _tool_contract_meta(meta: Mapping[str, Any] | None) -> object | None:
    return None if meta is None else meta.get(TOOL_CONTRACT_EXTENSION)


def _result_effect_unknown(result: CallToolResult, *, negotiated: bool) -> bool:
    if not negotiated:
        return result.is_error
    meta = result.meta or {}
    if TOOL_CONTRACT_EXTENSION not in meta:
        return False
    status = meta[TOOL_CONTRACT_EXTENSION]
    if not isinstance(status, Mapping) or set(status) != {"status"} or status.get("status") != "unknown":
        raise McpCallUnknownError("MCP Tool contract 结果元数据非法，调用效果无法确认")
    return True


__all__ = [
    "TOOL_CONTRACT_EXTENSION",
    "WORLD_EVENTS_EXTENSION",
    "WORLD_EVENT_NOTIFICATION",
    "McpClientFactory",
    "McpClientPort",
    "SdkMcpClientFactory",
]
