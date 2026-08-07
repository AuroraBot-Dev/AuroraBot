"""MCP 薄适配器：动态 Tool 发现、执行与 AMP 事件入口。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from mcp import types
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

from src.contracts import (
    AppConfig,
    AuroraConfig,
    CapabilityCatalogSnapshot,
    CapabilityDescriptor,
    ExternalAmpIngressPort,
    ToolExecutionRequest,
    ToolOutcome,
    ToolOutcomeStatus,
    new_amp,
)
from src.platform.mcp.client_manager import (
    MCPClientManager,
    MCPToolCallError,
    MCPToolRejectedError,
    _NotifiableClientSession,
)
from src.platform.mcp.server_kit import MCPServerKit
from src.platform.mcp.server_spec import MCPServerSpec
from src.utils import get_logger

logger = get_logger("aurora.platform.mcp")
_RESERVED_TOOL_EVENTS = frozenset({"tool.succeeded", "tool.failed", "tool.unknown"})


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    SHUTDOWN_RESTART_DENIED = "MCP 平台不可在关机后重启"
    UNKNOWN_CAPABILITY = "unknown MCP capability: {capability}"
    HEARTBEAT_REJECTED = "时钟心跳启动被拒绝"
    INVALID_RAW_NAME = "MCP tool 的 raw name 无效: {package}"
    MISSING_INPUT_SCHEMA = "MCP tool 缺少 input schema: {package}.{raw_name}"
    DUPLICATE_CAPABILITY = "MCP capability 重复: {capability}"
    REMOTE_SESSION_UNAVAILABLE = "远程 MCP 会话不可用: {package}"
    CONNECTION_LOST = "MCP 连接意外终止"


@dataclass(slots=True)
class _RemoteConnection:
    """远程 Streamable HTTP MCP 连接的内部状态。"""

    app: AppConfig
    session: _NotifiableClientSession | None = None
    tools: list[object] | None = None
    ready: asyncio.Event | None = None
    error: BaseException | None = None
    task: asyncio.Task[None] | None = None


class MCPPlatform:
    """拥有 MCP 会话管理，并将发现的原始 Tool 按 App 包暴露为能力。

    支持两种传输方式：
    - **stdio**：通过 MCPServerKit 管理本地子进程
    - **streamable_http**：通过 HTTP 直接连接远程 MCP Server
    """

    def __init__(self, configuration: AuroraConfig, *, terminal_logs: bool = True) -> None:
        """初始化 MCP 平台及其连接状态。"""
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
        self._remote_disconnected = asyncio.Event()
        self._notification_task: asyncio.Task[None] | None = None
        self._ingress: ExternalAmpIngressPort | None = None

    async def start(self, ingress: ExternalAmpIngressPort) -> CapabilityCatalogSnapshot:
        """启动 MCP 平台：连接所有 Server、发现 Tool、构建能力目录。

        启动流程：
        1. 启动所有本地 stdio Server
        2. 建立客户端连接并刷新工具列表
        3. 连接远程 HTTP Server
        4. 发现并注册所有能力
        5. 启动内置心跳

        Args:
            ingress: 外部 AMP 事件入口，用于转发 MCP 通知。

        Returns:
            当前可用的能力目录快照。
        """
        if self._started:
            return self._catalog
        if self._shutdown_complete:
            raise RuntimeError(_Msg.SHUTDOWN_RESTART_DENIED)
        self._ingress = ingress
        try:
            self._notification_task = asyncio.create_task(self._forward_local_notifications(), name="mcp-notifications")
            local_apps = [app for app in self._configuration.apps if app.transport == "stdio"]
            await self._kit.start_all([self._local_spec(app) for app in local_apps])
            await self._clients.connect_all({app.package: app.timeout_seconds for app in local_apps})
            remote_tasks = [
                asyncio.wait_for(self._connect_remote(app), timeout=app.timeout_seconds)
                for app in self._configuration.apps
                if app.transport == "streamable_http"
            ]
            if remote_tasks:
                await asyncio.gather(*remote_tasks)
            self._catalog = self._discover_capabilities()
            await self._start_builtin_heartbeat()
            self._started = True
        except BaseException:
            await self.shutdown()
            raise
        logger.info(
            "MCP 平台已启动 apps=%d capabilities=%d",
            len(self._configuration.apps),
            len(self._catalog.capabilities),
        )
        return self._catalog

    async def run(self, stop: asyncio.Event) -> None:
        """监视已建立连接；连接意外结束时让组合根关闭进程。"""
        waiters = {
            asyncio.create_task(stop.wait()),
            asyncio.create_task(self._clients.disconnected.wait()),
            asyncio.create_task(self._remote_disconnected.wait()),
        }
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            if not stop.is_set():
                raise RuntimeError(_Msg.CONNECTION_LOST)
        finally:
            for task in waiters:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        """当前已发现的能力目录快照（只读）。"""
        return self._catalog

    def source_instance_for(self, capability: str) -> str:
        """根据能力 ID 反查其所属的 App package。"""
        binding = self._tool_bindings.get(capability)
        if binding is None:
            raise ValueError(_Msg.UNKNOWN_CAPABILITY.format(capability=capability))
        package, _raw_name = binding
        return package

    def _local_spec(self, app: AppConfig) -> MCPServerSpec:
        """从 AppConfig 构造本地 stdio MCP Server 的启动规范。

        为内置时钟应用注入心跳节律参数（由运行时 autonomy 配置控制）。
        """
        environment = {"AURORA_APP_DATA_DIR": str(self._configuration.storage.apps)}
        environment.update({name: os.environ[name] for name in app.env_vars if name in os.environ})
        if app.package == "org.aurora.clock":
            autonomy = self._configuration.engine.autonomy
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
        """若已发现时钟应用能力，则启动内置心跳。"""
        capability = "org.aurora.clock.start_heartbeat"
        binding = self._tool_bindings.get(capability)
        if binding is None:
            return
        package, raw_name = binding
        result = await self._call_tool(package, raw_name, {})
        if result.get("is_error") is True:
            raise RuntimeError(_Msg.HEARTBEAT_REJECTED)

    async def _connect_remote(self, app: AppConfig) -> None:
        """建立到远程 Streamable HTTP MCP Server 的连接。

        创建后台连接任务并等待初始化完成（ready event 置位）。
        """
        connection = _RemoteConnection(app=app, ready=asyncio.Event())
        self._remote[app.package] = connection
        connection.task = asyncio.create_task(self._run_remote(connection), name=f"mcp-http-{app.package}")
        assert connection.ready is not None
        await connection.ready.wait()
        if connection.error is not None:
            message = f"MCP HTTP 连接失败 {app.package}: {connection.error}"
            raise RuntimeError(message) from connection.error

    async def _run_remote(self, connection: _RemoteConnection) -> None:
        """在后台运行远程 MCP Streamable HTTP 会话。

        负责：Bearer 认证、会话初始化、Tool 列表获取、等待停止信号。
        异常和正常结束均通过 ``ready`` event 和 ``error`` 字段报告。
        """
        headers: dict[str, str] = {}
        if connection.app.auth_env:
            token = os.getenv(connection.app.auth_env)
            if not token:
                connection.error = RuntimeError(f"缺少 MCP bearer 凭据: {connection.app.auth_env}")
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
                "远程 MCP 会话结束 package=%s error_type=%s",
                connection.app.package,
                type(error).__name__,
            )
            if connection.ready is not None and not connection.ready.is_set():
                connection.ready.set()
        finally:
            connection.session = None
            if not self._stop.is_set():
                self._remote_disconnected.set()

    def _discover_capabilities(self) -> CapabilityCatalogSnapshot:
        """扫描所有已连接 App 的 Tool 列表，构建统一能力目录。

        每个 Tool 的 ``name`` 与 App ``package`` 拼接形成唯一 capability ID。
        同时维护 ``_tool_bindings`` 用于后续 Tool 调用路由。
        """
        descriptors: dict[str, CapabilityDescriptor] = {}
        bindings: dict[str, tuple[str, str]] = {}
        for app in self._configuration.apps:
            for tool in self._tools_for_app(app.package):
                raw_name = getattr(tool, "name", None)
                if not isinstance(raw_name, str) or not raw_name:
                    raise RuntimeError(_Msg.INVALID_RAW_NAME.format(package=app.package))
                schema = getattr(tool, "inputSchema", None)
                if not isinstance(schema, dict):
                    raise RuntimeError(_Msg.MISSING_INPUT_SCHEMA.format(package=app.package, raw_name=raw_name))
                capability = f"{app.package}.{raw_name}"
                if capability in descriptors:
                    raise RuntimeError(_Msg.DUPLICATE_CAPABILITY.format(capability=capability))
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
        """获取指定 App 的 Tool 列表。

        优先查询远程 HTTP 连接缓存，其次查询本地 stdio 连接缓存。
        """
        remote = self._remote.get(package)
        if remote is not None:
            return remote.tools or []
        return list(self._clients.list_all_tools().get(package, []))

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        """执行 MCP Tool 调用：路由到正确的 Server 并返回结构化结果。

        根据 capability ID 路由到对应 App 和 raw tool name。
        支持 isError 检测并映射为失败结果。
        """
        if not self._started:
            return ToolOutcome(ToolOutcomeStatus.FAILED, "MCP Tool 不可用", error="MCP 平台尚未启动")
        binding = self._tool_bindings.get(request.capability)
        if binding is None:
            return ToolOutcome(
                ToolOutcomeStatus.FAILED, "MCP Tool 不可用", error=f"未知的 MCP capability: {request.capability}"
            )
        package, raw_name = binding
        if not self._is_connected(package):
            return ToolOutcome(ToolOutcomeStatus.FAILED, "MCP Tool 不可用", error=f"MCP App 未连接: {package}")
        try:
            result = await self._call_tool(package, raw_name, request.parameters)
        except Exception as error:
            if isinstance(error, MCPToolRejectedError) or (
                isinstance(error, McpError) and error.error.code != types.CONNECTION_CLOSED
            ):
                return ToolOutcome(
                    ToolOutcomeStatus.FAILED, f"MCP Tool 执行失败: {request.capability}", error=str(error)
                )
            logger.exception(
                "MCP Tool 结果未知 request_id=%s capability=%s error_type=%s",
                request.request_id,
                request.capability,
                type(error).__name__,
            )
            return ToolOutcome(
                ToolOutcomeStatus.UNKNOWN,
                f"MCP Tool 结果未知: {request.capability}",
                error=f"{type(error).__name__}: {error}",
            )
        if result.get("is_error") is True:
            detail = str(result.get("text") or result.get("content") or "MCP Tool 返回 isError")
            return ToolOutcome(ToolOutcomeStatus.FAILED, f"MCP Tool 执行失败: {request.capability}", error=detail)
        return ToolOutcome(
            ToolOutcomeStatus.SUCCEEDED,
            f"MCP Tool 已执行: {request.capability}",
            result=_canonical_tool_result(result),
        )

    async def _call_tool(self, package: str, raw_name: str, parameters: dict[str, Any]) -> dict[str, object]:
        """调用指定 App 上的 Tool（自动路由到远程 HTTP 或本地 stdio）。

        远程调用使用 ``streamablehttp_client`` 的连接会话；
        本地调用委托给 ``MCPClientManager.call_tool``。
        """
        remote = self._remote.get(package)
        if remote is not None:
            if remote.session is None:
                raise MCPToolCallError(_Msg.REMOTE_SESSION_UNAVAILABLE.format(package=package))
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

    def _is_connected(self, package: str) -> bool:
        """检查本地或远程 App 是否仍有活跃会话。"""
        remote = self._remote.get(package)
        return remote.session is not None if remote is not None else self._clients.is_connected(package)

    def _app_timeout(self, package: str) -> float:
        """查询指定 App 的配置超时秒数。"""
        return next(app.timeout_seconds for app in self._configuration.apps if app.package == package)

    async def _forward_local_notifications(self) -> None:
        """从通知队列中消费本地 stdio MCP 通知并转发给 handler。"""
        while not self._stop.is_set():
            package, method, params = await self._clients.notification_queue.get()
            try:
                await self._handle_notification(package, method, params)
            except Exception:
                logger.exception("畸形 MCP 通知已跳过 package=%s method=%s", package, method)

    async def _handle_notification(self, package: str, method: str, params: dict[str, object]) -> None:
        """处理来自 MCP Server 的通知：按类型转换为 AMP 事件并提交。

        支持两种通知格式：
        1. **Aurora 事件通知**（``notifications/message`` + ``logger=aurora/event``）
           → 解析事件 payload 并转换为 AMP 事件
        2. **通用 MCP 通知** → 包装为 ``mcp.notification`` 类型的事件

        保留类型（``tool.succeeded``、``tool.failed``、``tool.unknown``）会被跳过，
        以防止与本地 Tool 调用结果重复。
        """
        if self._ingress is None or not any(app.package == package for app in self._configuration.apps):
            return
        message_id: str | None = None
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
                logger.warning("保留的 MCP 事件已跳过 package=%s event_type=%s", package, event_type)
                return
            if not isinstance(session_id, str) or not session_id:
                return
            if not isinstance(summary, str) or not summary:
                return
            if not isinstance(data, dict):
                return
            identity = raw_event.get("idempotency_key")
            if not isinstance(identity, str) or not identity:
                identity = json.dumps(raw_event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            identity = json.dumps(
                {"package": package, "type": event_type, "session_id": session_id, "key": identity},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            message_id = str(uuid5(NAMESPACE_URL, f"aurora-mcp-event:{identity}"))
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
            message_id=message_id,
        )
        await self._ingress.submit_amp(event.to_dict())

    async def shutdown(self) -> None:
        """关闭 MCP 平台：取消通知任务、断开所有连接、停止所有 Server。

        使用锁保证只会执行一次关机流程。
        """
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
    """将 MCP Tool 调用结果转换为统一字典。"""
    content = getattr(result, "content", [])
    text = "\n".join(str(value) for item in content if (value := getattr(item, "text", None)) is not None)
    return {
        "is_error": bool(getattr(result, "isError", False)),
        "text": text,
        "content": [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in content],
        "structured_content": getattr(result, "structuredContent", None),
    }


def _canonical_tool_result(result: dict[str, object]) -> dict[str, Any]:
    """将 MCP 的多种等价结果表示压缩为单一模型上下文。"""
    structured = result.get("structured_content")
    if isinstance(structured, dict):
        return dict(structured)
    if structured is not None:
        return {"data": structured}
    text = result.get("text")
    if isinstance(text, str) and text.strip():
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
        return dict(parsed) if isinstance(parsed, dict) else {"data": parsed}
    content = result.get("content")
    return {"content": content} if content else {}
