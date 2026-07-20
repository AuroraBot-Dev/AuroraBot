"""Package-scoped MCP capability discovery and effect execution for AuroraBot."""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass

from mcp.client.streamable_http import streamablehttp_client

from src.contracts.agent import (
    CapabilityCatalogSnapshot,
    CapabilityDescriptor,
)
from src.contracts.amp import new_amp
from src.contracts.configuration import AppConfig, AuroraConfig
from src.localhost.ports import (
    EffectExecutionRequest,
    EffectOutcome,
    ExternalAmpIngressPort,
    PublicationExecutionRequest,
    PublicationOutcome,
)
from src.platform.mcp.client_manager import MCPClientManager, MCPToolCallError, _NotifiableClientSession
from src.platform.mcp.communication import (
    RAW_PUBLICATION_SCHEMA,
    CanonicalInboundMessage,
    CommunicationNotificationError,
    publication_descriptor_schema,
)
from src.platform.mcp.publication import MCPPublicationService
from src.platform.mcp.publication_ledger import MCPPublicationLedger
from src.platform.mcp.server_kit import MCPServerKit
from src.platform.mcp.server_spec import MCPServerSpec
from src.utils.log_utils import get_logger

logger = get_logger("aurora.platform.mcp")

_INTERNAL_RECEIPT_TYPES = {
    "effect.succeeded",
    "effect.failed",
}


@dataclass(slots=True)
class _RemoteConnection:
    app: AppConfig
    session: _NotifiableClientSession | None = None
    tools: list[object] | None = None
    ready: asyncio.Event | None = None
    error: BaseException | None = None
    task: asyncio.Task[None] | None = None


class MCPPlatform:
    """Own enabled MCP app sessions, discover their package-scoped tools, and execute effects."""

    def __init__(self, configuration: AuroraConfig, *, terminal_logs: bool = True) -> None:
        self._configuration = configuration
        self._kit = MCPServerKit(terminal_logs=terminal_logs)
        self._clients = MCPClientManager(self._kit)
        self._remote: dict[str, _RemoteConnection] = {}
        self._started = False
        self._shutdown_complete = False
        self._shutdown_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._notification_task: asyncio.Task[None] | None = None
        self._ingress: ExternalAmpIngressPort | None = None
        self._effect_catalog = CapabilityCatalogSnapshot()
        self._publication_catalog = CapabilityCatalogSnapshot()
        self._catalog = CapabilityCatalogSnapshot()
        self._ledger: MCPPublicationLedger | None = None
        self._publications: MCPPublicationService | None = None

    async def start(self, ingress: ExternalAmpIngressPort) -> CapabilityCatalogSnapshot:
        if self._started:
            logger.debug("MCP platform startup skipped reason=already_started")
            return self.capability_catalog
        if self._shutdown_complete:
            raise RuntimeError("MCP platform cannot restart after shutdown")
        logger.info("MCP platform startup started apps=%d", len(self._configuration.apps))
        self._ingress = ingress
        try:
            if any(app.kind == "communication" for app in self._configuration.apps):
                self._ledger = MCPPublicationLedger(
                    self._configuration.root / "data" / "platform" / "mcp" / "publications.sqlite3"
                )
                self._publications = MCPPublicationService(self._configuration, self._ledger, self._call_tool)
            startup_timeout = max((app.timeout_seconds for app in self._configuration.apps), default=30.0)
            local_specs = [self._local_spec(app) for app in self._configuration.apps if app.transport == "stdio"]
            await self._kit.start_all(local_specs)
            await asyncio.wait_for(self._clients.connect_all(), timeout=startup_timeout)
            await asyncio.wait_for(self._clients.refresh_tools(), timeout=startup_timeout)
            remote_tasks = [
                self._connect_remote(app) for app in self._configuration.apps if app.transport == "streamable_http"
            ]
            if remote_tasks:
                await asyncio.wait_for(asyncio.gather(*remote_tasks), timeout=startup_timeout)
            self._effect_catalog, self._publication_catalog = self._discover_capabilities()
            self._catalog = CapabilityCatalogSnapshot(
                self._effect_catalog.capabilities + self._publication_catalog.capabilities
            )
            self._notification_task = asyncio.create_task(self._forward_local_notifications(), name="mcp-notifications")
            self._started = True
        except BaseException:
            await self.shutdown()
            raise
        logger.info(
            "MCP platform startup completed local_apps=%d remote_apps=%d capabilities=%d",
            sum(app.transport == "stdio" for app in self._configuration.apps),
            sum(app.transport == "streamable_http" for app in self._configuration.apps),
            len(self.capability_catalog.capabilities),
        )
        return self.capability_catalog

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        return self._catalog

    @property
    def effect_catalog(self) -> CapabilityCatalogSnapshot:
        return self._effect_catalog

    @property
    def publication_catalog(self) -> CapabilityCatalogSnapshot:
        return self._publication_catalog

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

    def _discover_capabilities(self) -> tuple[CapabilityCatalogSnapshot, CapabilityCatalogSnapshot]:
        effect_descriptors: dict[str, CapabilityDescriptor] = {}
        publication_descriptors: dict[str, CapabilityDescriptor] = {}
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
                configured = next(item for item in app.tools if item.name == name)
                if configured.kind == "effect":
                    if name in effect_descriptors:
                        raise RuntimeError(f"duplicate MCP effect capability: {name}")
                    effect_descriptors[name] = CapabilityDescriptor(
                        name,
                        str(getattr(tool, "description", "") or ""),
                        dict(schema),
                    )
                    continue
                if app.kind != "communication" or schema != RAW_PUBLICATION_SCHEMA:
                    raise RuntimeError(f"MCP publication tool has non-canonical input schema: {name}")
            raw_descriptions = {
                str(getattr(tool, "name", "")): str(getattr(tool, "description", "") or "") for tool in tools
            }
            for publication in app.publications:
                if publication.capability in publication_descriptors:
                    raise RuntimeError(f"duplicate MCP publication capability: {publication.capability}")
                publication_descriptors[publication.capability] = CapabilityDescriptor(
                    id=publication.capability,
                    description=raw_descriptions[publication.tool],
                    parameters_schema=publication_descriptor_schema(publication.operation),
                    kind="publication",
                    endpoint=app.package,
                    operation=publication.operation,
                    root_only=True,
                )
        effects = tuple(sorted(effect_descriptors.values(), key=lambda item: item.id))
        publications = tuple(sorted(publication_descriptors.values(), key=lambda item: item.id))
        return CapabilityCatalogSnapshot(effects), CapabilityCatalogSnapshot(publications)

    def _tools_for_app(self, package: str) -> list[object]:
        remote = self._remote.get(package)
        if remote is not None:
            return remote.tools or []
        return list(self._clients.list_all_tools().get(package, []))

    async def execute_effect(self, request: EffectExecutionRequest) -> EffectOutcome:
        if not self._started:
            return EffectOutcome(
                succeeded=False,
                summary="MCP capability unavailable",
                error="MCP platform is not started",
            )
        capability = request.capability
        logger.debug(
            "MCP effect started request_id=%s capability=%s parameter_keys=%s",
            request.request_id,
            capability,
            sorted(request.parameters),
        )
        try:
            result = await self._call_tool(capability, request.parameters)
            _require_successful_tool_result(result)
            return EffectOutcome(
                succeeded=True,
                summary=f"MCP capability completed: {capability}",
                result=result,
            )
        except Exception as error:
            logger.exception(
                "MCP effect failed request_id=%s capability=%s error_type=%s",
                request.request_id,
                capability,
                type(error).__name__,
            )
            return EffectOutcome(
                succeeded=False,
                summary=f"MCP capability failed: {capability}",
                error=f"{type(error).__name__}: {error}",
            )

    async def execute_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        if not self._started or self._publications is None:
            return PublicationOutcome(
                "failed",
                "MCP Publication unavailable",
                error="MCP platform is not started for a communication App",
            )
        return await self._publications.execute(request)

    async def recover_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        if self._publications is None:
            return PublicationOutcome(
                "failed",
                "MCP Publication was interrupted before dispatch",
                error="interrupted_before_dispatch",
            )
        return await self._publications.recover(request)

    async def _call_tool(self, capability: str, parameters: dict[str, object]) -> dict[str, object]:
        package = self._package_for_tool(capability)
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

    def _package_for_tool(self, tool_name: str) -> str:
        matches = [app.package for app in self._configuration.apps if tool_name.startswith(f"{app.package}.")]
        if not matches:
            raise MCPToolCallError(f"MCP tool is outside configured package namespaces: {tool_name}")
        return max(matches, key=len)

    async def _forward_local_notifications(self) -> None:
        while not self._stop.is_set():
            package, method, params = await self._clients.notification_queue.get()
            try:
                await self._handle_notification(package, method, params)
            except Exception:
                logger.exception("MCP notification worker rejected an event package=%s method=%s", package, method)

    async def _handle_notification(  # noqa: PLR0912
        self, package: str, method: str, params: dict[str, object]
    ) -> None:
        if method == "notifications/message" and params.get("logger") == "aurora/event":
            payload = params.get("data")
            if not isinstance(payload, dict):
                return
            method = "aurora/event"
            params = payload
        if method != "aurora/event" or self._ingress is None:
            logger.debug("MCP notification ignored package=%s method=%s", package, method)
            return
        app = next((item for item in self._configuration.apps if item.package == package), None)
        if app is None:
            logger.warning("MCP notification rejected from unknown package=%s", package)
            return
        event_type = params.get("type")
        if event_type in _INTERNAL_RECEIPT_TYPES or (
            isinstance(event_type, str) and event_type.startswith("publication.")
        ):
            logger.warning("MCP notification rejected internal receipt package=%s event_type=%s", package, event_type)
            return
        if event_type == "message.received":
            if app.kind != "communication" or self._ledger is None:
                logger.warning("MCP message.received rejected from utility package=%s", package)
                return
            try:
                inbound = CanonicalInboundMessage.parse(package, params)
            except CommunicationNotificationError as error:
                logger.warning("malformed MCP communication notification package=%s error=%s", package, error)
                return
            observation, detail = self._ledger.observe_delivery(
                package, inbound.external_message_id, inbound.origin_delivery_id
            )
            if observation == "observed":
                return
            if observation == "quarantine":
                self._quarantine(inbound, detail or "inbound delivery metadata conflicts with local ledger")
                return
            if inbound.authored_by_self:
                self._quarantine(inbound, "self-authored message has no local delivery record")
                return
            event = inbound.to_amp()
        else:
            data = params.get("data", {})
            if not isinstance(event_type, str) or not event_type or not isinstance(data, dict):
                return
            if _contains_communication_route(data):
                logger.warning(
                    "MCP non-message notification rejected communication route package=%s event_type=%s",
                    package,
                    event_type,
                )
                return
            event = new_amp(
                event_type=event_type,
                session_id=str(params.get("session_id", package)),
                summary=str(params.get("summary", event_type)),
                data=data,
                source_app=package,
                source_instance=f"mcp:{package}",
            )
        await self._ingress.submit_amp(event.to_dict())
        logger.debug(
            "MCP event forwarded package=%s method=%s message_id=%s event_type=%s",
            package,
            method,
            event.header.message_id,
            event_type,
        )

    def _quarantine(self, inbound: CanonicalInboundMessage, reason: str) -> None:
        assert self._ledger is not None
        self._ledger.quarantine(
            endpoint_id=inbound.endpoint_id,
            external_event_id=inbound.external_event_id,
            external_message_id=inbound.external_message_id,
            origin_delivery_id=inbound.origin_delivery_id,
            authored_by_self=inbound.authored_by_self,
            reason=reason,
        )
        logger.warning(
            "MCP inbound communication quarantined package=%s external_event_id=%s reason=%s",
            inbound.endpoint_id,
            inbound.external_event_id,
            reason,
        )

    async def shutdown(self) -> None:
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return
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
            if self._ledger is not None:
                self._ledger.close()
                self._ledger = None
                self._publications = None
            self._started = False
            self._ingress = None
            self._shutdown_complete = True
            logger.info("MCP platform shutdown completed")


def _tool_result(result: object) -> dict[str, object]:
    content = getattr(result, "content", [])
    return {
        "ok": not bool(getattr(result, "isError", False)),
        "is_error": bool(getattr(result, "isError", False)),
        "content": [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in content],
        "structured_content": getattr(result, "structuredContent", None),
    }


def _require_successful_tool_result(result: dict[str, object]) -> None:
    if result.get("is_error") is not True:
        return
    detail = result.get("text") or result.get("content") or "MCP tool returned isError"
    raise MCPToolCallError(str(detail))


def _contains_communication_route(value: object) -> bool:
    if isinstance(value, dict):
        if any(key in {"communication", "reply_route", "reply_route_ref"} for key in value):
            return True
        return any(_contains_communication_route(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_communication_route(item) for item in value)
    return False
