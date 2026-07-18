"""Package-scoped MCP capability discovery and effect execution for AuroraBot."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from mcp.client.streamable_http import streamablehttp_client

from src.contracts.agent import (
    CapabilityCatalogSnapshot,
    CapabilityDescriptor,
    EffectLease,
    PlatformRuntimePort,
)
from src.contracts.amp import AmpEnvelope, new_amp
from src.contracts.configuration import AppConfig, AuroraConfig, CapabilityConfig
from src.platform.effects import PlatformRunResult
from src.platform.mcp.client_manager import MCPClientManager, MCPToolCallError, _NotifiableClientSession
from src.platform.mcp.server_kit import MCPServerKit
from src.platform.mcp.server_spec import MCPServerSpec
from src.utils.log_utils import get_logger

logger = get_logger("aurora.platform.mcp")


@dataclass(slots=True)
class _RemoteConnection:
    app: AppConfig
    session: _NotifiableClientSession | None = None
    tools: list[object] | None = None
    ready: asyncio.Event | None = None
    error: BaseException | None = None
    task: asyncio.Task[None] | None = None


ToolResultObserver = Callable[[str, dict[str, object]], None]


class MCPPlatform:
    """Own enabled MCP app sessions, discover their package-scoped tools, and execute effects."""

    def __init__(self, configuration: AuroraConfig, *, tool_result_observer: ToolResultObserver | None = None) -> None:
        self._configuration = configuration
        self._kit = MCPServerKit()
        self._clients = MCPClientManager(self._kit)
        self._remote: dict[str, _RemoteConnection] = {}
        self._started = False
        self._stop = asyncio.Event()
        self._notification_task: asyncio.Task[None] | None = None
        self._kernel: PlatformRuntimePort | None = None
        self._tool_result_observer = tool_result_observer
        self._catalog = CapabilityCatalogSnapshot()

    def set_tool_result_observer(self, observer: ToolResultObserver | None) -> None:
        """Set the localhost-only observer for successfully completed MCP tools."""
        self._tool_result_observer = observer

    async def start(self, kernel: PlatformRuntimePort) -> None:
        if self._started:
            logger.debug("MCP platform startup skipped reason=already_started")
            return
        logger.info("MCP platform startup started apps=%d", len(self._configuration.apps))
        self._kernel = kernel
        local_specs = [self._local_spec(app) for app in self._configuration.apps if app.transport == "stdio"]
        await self._kit.start_all(local_specs)
        await self._clients.connect_all()
        await self._clients.refresh_tools()
        remote_tasks = [
            self._connect_remote(app) for app in self._configuration.apps if app.transport == "streamable_http"
        ]
        if remote_tasks:
            await asyncio.gather(*remote_tasks)
        self._catalog = self._discover_capabilities()
        kernel.install_capability_catalog(self._catalog)
        # Convenient ID view for callers; Kernel uses the immutable catalog above.
        self._configuration.capability_definitions.update(
            {
                item.id: CapabilityConfig(item.id, item.parameters_schema, item.description, item.result_mode)
                for item in self._catalog.capabilities
            }
        )
        self._notification_task = asyncio.create_task(self._forward_local_notifications(), name="mcp-notifications")
        self._started = True
        logger.info(
            "MCP platform startup completed local_apps=%d remote_apps=%d capabilities=%d",
            sum(app.transport == "stdio" for app in self._configuration.apps),
            sum(app.transport == "streamable_http" for app in self._configuration.apps),
            len(self._catalog.capabilities),
        )

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        return self._catalog

    def _local_spec(self, app: AppConfig) -> MCPServerSpec:
        return MCPServerSpec(
            key=app.package,
            package=app.package,
            name=app.package,
            directory=app.working_dir or self._configuration.root,
            command=list(app.command),
            env={"AURORA_APP_DATA_DIR": str(self._configuration.root / "data" / "app_data")},
            health_timeout_seconds=app.timeout_seconds,
        )

    async def _connect_remote(self, app: AppConfig) -> None:
        connection = _RemoteConnection(app=app, ready=asyncio.Event())
        self._remote[app.package] = connection
        connection.task = asyncio.create_task(self._run_remote(connection), name=f"mcp-http-{app.package}")
        assert connection.ready is not None
        await connection.ready.wait()
        if connection.error is not None:
            logger.error(
                "remote MCP connection failed package=%s error_type=%s",
                app.package,
                type(connection.error).__name__,
            )
            message = f"MCP HTTP connection failed for {app.package}: {connection.error}"
            raise RuntimeError(message) from connection.error
        logger.info("remote MCP connection ready package=%s tools=%d", app.package, len(connection.tools or []))

    async def _run_remote(self, connection: _RemoteConnection) -> None:
        headers: dict[str, str] = {}
        if connection.app.auth_env:
            token = os.getenv(connection.app.auth_env)
            if not token:
                connection.error = RuntimeError(f"missing MCP bearer credential: {connection.app.auth_env}")
                logger.warning(
                    "remote MCP credential unavailable package=%s credential_env=%s",
                    connection.app.package,
                    connection.app.auth_env,
                )
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
        for app in self._configuration.apps:
            tools = self._tools_for_app(app.package)
            discovered = {str(getattr(tool, "name", "")): tool for tool in tools}
            if set(discovered) != set(app.allowed_tools):
                raise RuntimeError(f"MCP tool allowlist mismatch for {app.package}: {sorted(discovered)}")
            for name, tool in discovered.items():
                if not name.startswith(f"{app.package}."):
                    raise RuntimeError(f"MCP tool is outside package namespace: {name}")
                schema = getattr(tool, "inputSchema", None)
                if not isinstance(schema, dict):
                    raise RuntimeError(f"MCP tool lacks input schema: {name}")
                if name in descriptors:
                    raise RuntimeError(f"duplicate MCP capability: {name}")
                configured = next(item for item in app.tools if item.name == name)
                descriptors[name] = CapabilityDescriptor(
                    name,
                    str(getattr(tool, "description", "") or ""),
                    dict(schema),
                    configured.result_mode,
                )
                logger.debug(
                    "MCP capability discovered package=%s capability=%s result_mode=%s",
                    app.package,
                    name,
                    configured.result_mode,
                )
        return CapabilityCatalogSnapshot(tuple(sorted(descriptors.values(), key=lambda item: item.id)))

    def _tools_for_app(self, package: str) -> list[object]:
        remote = self._remote.get(package)
        if remote is not None:
            return remote.tools or []
        return list(self._clients.list_all_tools().get(package, []))

    async def execute_pending_effects(self, kernel: PlatformRuntimePort) -> PlatformRunResult:
        if not self._started:
            return PlatformRunResult(0)
        capabilities = frozenset(capability for app in self._configuration.apps for capability in app.allowed_tools)
        records = await kernel.claim_effect_requests(capabilities)
        completed = await asyncio.gather(*(self._execute_one(kernel, record) for record in records))
        return PlatformRunResult(sum(completed))

    async def _execute_one(self, kernel: PlatformRuntimePort, record: EffectLease) -> int:
        started = time.monotonic()
        amp = AmpEnvelope.parse(record.amp)
        data = amp.payload.data
        request_id = data.get("request_id")
        capability = data.get("capability")
        parameters = data.get("parameters")
        if not isinstance(request_id, str) or not isinstance(capability, str) or not isinstance(parameters, dict):
            await kernel.complete_effect(record, error="invalid effect.requested payload")
            logger.error(
                "invalid MCP effect request activity_id=%s task_id=%s request_id=%s capability=%s",
                record.record_id,
                record.task_id,
                request_id,
                capability,
            )
            return 0
        logger.debug(
            "MCP effect started activity_id=%s task_id=%s request_id=%s capability=%s parameter_keys=%s",
            record.record_id,
            record.task_id,
            request_id,
            capability,
            sorted(parameters),
        )
        try:
            result = await self._call_tool(capability, parameters)
            if self._tool_result_observer is not None:
                self._tool_result_observer(capability, result)
            receipt = new_amp(
                event_type="effect.succeeded",
                session_id=amp.payload.session_id,
                summary=f"MCP capability completed: {capability}",
                data={"request_id": request_id, "capability": capability, "result": result},
                source_app="platform.mcp",
                source_instance=capability.rpartition(".")[0],
            )
            await kernel.submit_amp(receipt)
            await kernel.complete_effect(record)
            logger.info(
                "MCP effect succeeded activity_id=%s task_id=%s request_id=%s capability=%s duration_ms=%.1f",
                record.record_id,
                record.task_id,
                request_id,
                capability,
                (time.monotonic() - started) * 1000,
            )
        except Exception as error:
            receipt = new_amp(
                event_type="effect.failed",
                session_id=amp.payload.session_id,
                summary=f"MCP capability failed: {capability}",
                data={
                    "request_id": request_id,
                    "capability": capability,
                    "error": f"{type(error).__name__}: {error}",
                },
                source_app="platform.mcp",
                source_instance=capability.rpartition(".")[0],
            )
            await kernel.submit_amp(receipt)
            await kernel.complete_effect(record, error=f"{type(error).__name__}: {error}")
            logger.log(
                logging.ERROR,
                "MCP effect failed activity_id=%s task_id=%s request_id=%s "
                "capability=%s duration_ms=%.1f error_type=%s",
                record.record_id,
                record.task_id,
                request_id,
                capability,
                (time.monotonic() - started) * 1000,
                type(error).__name__,
            )
        return 1

    async def _call_tool(self, capability: str, parameters: dict[str, object]) -> dict[str, object]:
        package, _, _tool = capability.rpartition(".")
        remote = self._remote.get(package)
        if remote is not None:
            if remote.session is None:
                raise MCPToolCallError(f"remote MCP session unavailable: {package}")
            result = await asyncio.wait_for(
                remote.session.call_tool(capability, parameters), timeout=remote.app.timeout_seconds
            )
            return _tool_result(result)
        return await self._clients.call_tool(capability, parameters, timeout_seconds=self._app_timeout(package))

    def _app_timeout(self, package: str) -> float:
        return next(app.timeout_seconds for app in self._configuration.apps if app.package == package)

    async def _forward_local_notifications(self) -> None:
        while not self._stop.is_set():
            package, method, params = await self._clients.notification_queue.get()
            await self._handle_notification(package, method, params)

    async def _handle_notification(self, package: str, method: str, params: dict[str, object]) -> None:
        if method == "notifications/message" and params.get("logger") == "aurora/event":
            payload = params.get("data")
            if not isinstance(payload, dict):
                return
            method = "aurora/event"
            params = payload
        if method != "aurora/event" or self._kernel is None:
            logger.debug("MCP notification ignored package=%s method=%s", package, method)
            return
        event_type = params.get("type")
        data = params.get("data", {})
        if not isinstance(event_type, str) or not isinstance(data, dict):
            return
        event = new_amp(
            event_type=event_type,
            session_id=str(params.get("session_id", package)),
            summary=str(params.get("summary", event_type)),
            data=data,
            source_app=package,
            source_instance="mcp",
        )
        await self._kernel.submit_amp(event)
        logger.debug(
            "MCP event forwarded package=%s method=%s message_id=%s event_type=%s",
            package,
            method,
            event.header.message_id,
            event_type,
        )

    async def shutdown(self) -> None:
        if not self._started:
            logger.debug("MCP platform shutdown skipped reason=not_started")
        else:
            logger.info("MCP platform shutdown started remote_connections=%d", len(self._remote))
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
        logger.info("MCP platform shutdown completed")


def _tool_result(result: object) -> dict[str, object]:
    content = getattr(result, "content", [])
    return {
        "ok": not bool(getattr(result, "isError", False)),
        "is_error": bool(getattr(result, "isError", False)),
        "content": [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in content],
        "structured_content": getattr(result, "structuredContent", None),
    }
