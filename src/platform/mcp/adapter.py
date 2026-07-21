"""Thin MCP adapter for dynamic Tool discovery, execution, and AMP ingress."""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass
from typing import Any

from mcp.client.streamable_http import streamablehttp_client

from src.contracts.agent import CapabilityCatalogSnapshot, CapabilityDescriptor
from src.contracts.amp import new_amp
from src.contracts.configuration import AppConfig, AuroraConfig
from src.localhost.ports import ExternalAmpIngressPort, ToolExecutionRequest, ToolOutcome
from src.platform.mcp.client_manager import MCPClientManager, MCPToolCallError, _NotifiableClientSession
from src.platform.mcp.server_kit import MCPServerKit
from src.platform.mcp.server_spec import MCPServerSpec
from src.utils.log_utils import get_logger

logger = get_logger("aurora.platform.mcp")
_RESERVED_TOOL_EVENTS = frozenset({"tool.succeeded", "tool.failed", "tool.unknown"})


@dataclass(slots=True)
class _RemoteConnection:
    app: AppConfig
    session: _NotifiableClientSession | None = None
    tools: list[object] | None = None
    ready: asyncio.Event | None = None
    error: BaseException | None = None
    task: asyncio.Task[None] | None = None


class MCPPlatform:
    """Own MCP sessions and expose every discovered raw Tool under its App package."""

    def __init__(self, configuration: AuroraConfig, *, terminal_logs: bool = True) -> None:
        self._configuration = configuration
        self._kit = MCPServerKit(terminal_logs=terminal_logs)
        self._clients = MCPClientManager(self._kit)
        self._remote: dict[str, _RemoteConnection] = {}
        self._tool_bindings: dict[str, tuple[str, str]] = {}
        self._catalog = CapabilityCatalogSnapshot()
        self._started = False
        self._shutdown_complete = False
        self._shutdown_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._notification_task: asyncio.Task[None] | None = None
        self._ingress: ExternalAmpIngressPort | None = None

    async def start(self, ingress: ExternalAmpIngressPort) -> CapabilityCatalogSnapshot:
        if self._started:
            return self._catalog
        if self._shutdown_complete:
            raise RuntimeError("MCP platform cannot restart after shutdown")
        self._ingress = ingress
        try:
            startup_timeout = max((app.timeout_seconds for app in self._configuration.apps), default=30.0)
            await self._kit.start_all(
                [self._local_spec(app) for app in self._configuration.apps if app.transport == "stdio"]
            )
            await asyncio.wait_for(self._clients.connect_all(), timeout=startup_timeout)
            await asyncio.wait_for(self._clients.refresh_tools(), timeout=startup_timeout)
            remote_tasks = [
                self._connect_remote(app) for app in self._configuration.apps if app.transport == "streamable_http"
            ]
            if remote_tasks:
                await asyncio.wait_for(asyncio.gather(*remote_tasks), timeout=startup_timeout)
            self._catalog = self._discover_capabilities()
            await self._start_builtin_heartbeat()
            self._notification_task = asyncio.create_task(self._forward_local_notifications(), name="mcp-notifications")
            self._started = True
        except BaseException:
            await self.shutdown()
            raise
        logger.info(
            "MCP platform started apps=%d capabilities=%d",
            len(self._configuration.apps),
            len(self._catalog.capabilities),
        )
        return self._catalog

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        return self._catalog

    def source_instance_for(self, capability: str) -> str:
        binding = self._tool_bindings.get(capability)
        if binding is None:
            raise ValueError(f"unknown MCP capability: {capability}")
        package, _raw_name = binding
        return package

    def _local_spec(self, app: AppConfig) -> MCPServerSpec:
        environment = {"AURORA_APP_DATA_DIR": str(self._configuration.root / "data" / "app_data")}
        if app.package == "org.aurora.clock":
            autonomy = self._configuration.runtime.autonomy
            environment.update(
                {
                    "AURORA_CLOCK_HEARTBEAT_INITIAL_SECONDS": str(autonomy.heartbeat_initial_seconds),
                    "AURORA_CLOCK_HEARTBEAT_MIN_SECONDS": str(autonomy.heartbeat_min_seconds),
                    "AURORA_CLOCK_HEARTBEAT_MAX_SECONDS": str(autonomy.heartbeat_max_seconds),
                }
            )
        return MCPServerSpec(
            key=app.package,
            package=app.package,
            name=app.package,
            directory=app.working_dir or self._configuration.root,
            command=list(app.command),
            env=environment,
            health_timeout_seconds=app.timeout_seconds,
        )

    async def _start_builtin_heartbeat(self) -> None:
        capability = "org.aurora.clock.start_heartbeat"
        binding = self._tool_bindings.get(capability)
        if binding is None:
            return
        package, raw_name = binding
        result = await self._call_tool(package, raw_name, {})
        if result.get("is_error") is True:
            raise RuntimeError("Clock heartbeat startup was rejected")

    async def _connect_remote(self, app: AppConfig) -> None:
        connection = _RemoteConnection(app=app, ready=asyncio.Event())
        self._remote[app.package] = connection
        connection.task = asyncio.create_task(self._run_remote(connection), name=f"mcp-http-{app.package}")
        assert connection.ready is not None
        await connection.ready.wait()
        if connection.error is not None:
            message = f"MCP HTTP connection failed for {app.package}: {connection.error}"
            raise RuntimeError(message) from connection.error

    async def _run_remote(self, connection: _RemoteConnection) -> None:
        headers: dict[str, str] = {}
        if connection.app.auth_env:
            token = os.getenv(connection.app.auth_env)
            if not token:
                connection.error = RuntimeError(f"missing MCP bearer credential: {connection.app.auth_env}")
                assert connection.ready is not None
                connection.ready.set()
                return
            headers["Authorization"] = f"Bearer {token}"
        try:
            assert connection.app.url is not None
            async with streamablehttp_client(
                connection.app.url,
                headers=headers,
                timeout=connection.app.timeout_seconds,
            ) as streams:
                read_stream, write_stream, _get_session_id = streams
                async with _NotifiableClientSession(
                    read_stream,
                    write_stream,
                    server_key=connection.app.package,
                    notification_dispatcher=self._handle_notification,
                ) as session:
                    await session.initialize()
                    connection.session = session
                    connection.tools = list((await session.list_tools()).tools)
                    assert connection.ready is not None
                    connection.ready.set()
                    await self._stop.wait()
        except Exception as error:
            connection.error = error
            logger.warning(
                "remote MCP session ended package=%s error_type=%s",
                connection.app.package,
                type(error).__name__,
            )
            if connection.ready is not None and not connection.ready.is_set():
                connection.ready.set()
        finally:
            connection.session = None

    def _discover_capabilities(self) -> CapabilityCatalogSnapshot:
        descriptors: dict[str, CapabilityDescriptor] = {}
        bindings: dict[str, tuple[str, str]] = {}
        for app in self._configuration.apps:
            for tool in self._tools_for_app(app.package):
                raw_name = getattr(tool, "name", None)
                if not isinstance(raw_name, str) or not raw_name:
                    raise RuntimeError(f"MCP tool has an invalid raw name: {app.package}")
                schema = getattr(tool, "inputSchema", None)
                if not isinstance(schema, dict):
                    raise RuntimeError(f"MCP tool lacks input schema: {app.package}.{raw_name}")
                capability = f"{app.package}.{raw_name}"
                if capability in descriptors:
                    raise RuntimeError(f"duplicate MCP capability: {capability}")
                description = getattr(tool, "description", "")
                descriptors[capability] = CapabilityDescriptor(
                    capability,
                    description if isinstance(description, str) else "",
                    schema,
                )
                bindings[capability] = (app.package, raw_name)
        self._tool_bindings = bindings
        return CapabilityCatalogSnapshot(tuple(sorted(descriptors.values(), key=lambda item: item.id)))

    def _tools_for_app(self, package: str) -> list[object]:
        remote = self._remote.get(package)
        if remote is not None:
            return remote.tools or []
        return list(self._clients.list_all_tools().get(package, []))

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        if not self._started:
            return ToolOutcome("failed", "MCP Tool unavailable", error="MCP platform is not started")
        binding = self._tool_bindings.get(request.capability)
        if binding is None:
            return ToolOutcome("failed", "MCP Tool unavailable", error=f"unknown MCP capability: {request.capability}")
        package, raw_name = binding
        try:
            result = await self._call_tool(package, raw_name, request.parameters)
        except Exception as error:
            logger.exception(
                "MCP Tool outcome unknown request_id=%s capability=%s error_type=%s",
                request.request_id,
                request.capability,
                type(error).__name__,
            )
            return ToolOutcome(
                "unknown",
                f"MCP Tool result unknown: {request.capability}",
                error=f"{type(error).__name__}: {error}",
            )
        if result.get("is_error") is True:
            detail = str(result.get("text") or result.get("content") or "MCP Tool returned isError")
            return ToolOutcome("failed", f"MCP Tool failed: {request.capability}", error=detail)
        return ToolOutcome("succeeded", f"MCP Tool completed: {request.capability}", result=result)

    async def _call_tool(self, package: str, raw_name: str, parameters: dict[str, Any]) -> dict[str, object]:
        remote = self._remote.get(package)
        if remote is not None:
            if remote.session is None:
                raise MCPToolCallError(f"remote MCP session unavailable: {package}")
            result = await asyncio.wait_for(
                remote.session.call_tool(raw_name, parameters), timeout=remote.app.timeout_seconds
            )
            return _tool_result(result)
        return await self._clients.call_tool(
            package,
            raw_name,
            parameters,
            timeout_seconds=self._app_timeout(package),
        )

    def _app_timeout(self, package: str) -> float:
        return next(app.timeout_seconds for app in self._configuration.apps if app.package == package)

    async def _forward_local_notifications(self) -> None:
        while not self._stop.is_set():
            package, method, params = await self._clients.notification_queue.get()
            try:
                await self._handle_notification(package, method, params)
            except Exception:
                logger.exception("malformed MCP notification skipped package=%s method=%s", package, method)

    async def _handle_notification(self, package: str, method: str, params: dict[str, object]) -> None:
        if self._ingress is None or not any(app.package == package for app in self._configuration.apps):
            return
        if method == "notifications/message" and params.get("logger") == "aurora/event":
            raw_event = params.get("data")
            if not isinstance(raw_event, dict):
                return
            event_type = raw_event.get("type")
            session_id = raw_event.get("session_id", package)
            summary = raw_event.get("summary", event_type)
            data = raw_event.get("data", {})
            if not isinstance(event_type, str) or not event_type:
                return
            if event_type in _RESERVED_TOOL_EVENTS:
                logger.warning("reserved MCP event skipped package=%s event_type=%s", package, event_type)
                return
            if not isinstance(session_id, str) or not session_id:
                return
            if not isinstance(summary, str) or not summary:
                return
            if not isinstance(data, dict):
                return
        else:
            if not isinstance(method, str) or not method or not isinstance(params, dict):
                return
            event_type = "mcp.notification"
            session_id = package
            summary = method
            data = {"method": method, "params": params}
        event = new_amp(
            event_type=event_type,
            session_id=session_id,
            summary=summary,
            data=data,
            source_app=package,
            source_instance=f"mcp:{package}",
        )
        await self._ingress.submit_amp(event.to_dict())

    async def shutdown(self) -> None:
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._stop.set()
            if self._notification_task is not None:
                self._notification_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._notification_task
            for connection in self._remote.values():
                if connection.task is not None:
                    connection.task.cancel()
            await asyncio.gather(
                *(connection.task for connection in self._remote.values() if connection.task is not None),
                return_exceptions=True,
            )
            await self._clients.shutdown()
            await self._kit.stop_all()
            self._started = False
            self._ingress = None
            self._shutdown_complete = True


def _tool_result(result: object) -> dict[str, object]:
    content = getattr(result, "content", [])
    text = "\n".join(str(value) for item in content if (value := getattr(item, "text", None)) is not None)
    return {
        "is_error": bool(getattr(result, "isError", False)),
        "text": text,
        "content": [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in content],
        "structured_content": getattr(result, "structuredContent", None),
    }
