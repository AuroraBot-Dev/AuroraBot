# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from src.config.loader import load_configuration
from src.contracts.amp import AmpEnvelope
from src.contracts.tool import ToolExecutionRequest
from src.platform.mcp import MCPPlatform
from src.platform.mcp.client_manager import ClientConnection, MCPClientManager, MCPToolCallError

if TYPE_CHECKING:
    from pathlib import Path


class _ConnectionLostError(TimeoutError):
    pass


@dataclass(slots=True)
class _Ingress:
    values: list[object] = field(default_factory=list)

    async def submit_amp(self, value: object) -> str:
        self.values.append(value)
        return AmpEnvelope.parse(value).header.message_id


class _FakeKit:
    async def start_all(self, _specs: object) -> None:
        pass

    async def stop_all(self) -> None:
        pass


class _FakeClients:
    def __init__(self, tools: dict[str, list[object]]) -> None:
        self.tools = tools
        self.notification_queue: asyncio.Queue[tuple[str, str, dict[str, object]]] = asyncio.Queue()

    async def connect_all(self) -> None:
        pass

    async def refresh_tools(self) -> None:
        pass

    def list_all_tools(self) -> dict[str, list[object]]:
        return self.tools

    async def shutdown(self) -> None:
        pass


def _write_apps(project_root: Path, *packages: str) -> None:
    entries = [
        f"""[[app]]
package = "{package}"
enabled = true
transport = "stdio"
working_dir = "."
command = ["python", "server.py"]
timeout_seconds = 30
"""
        for package in packages
    ]
    (project_root / "config" / "apps.toml").write_text("\n".join(entries) or "app = []\n", encoding="utf-8")


def _tool(name: str, description: str = "raw description", schema: dict[str, Any] | None = None) -> object:
    return SimpleNamespace(name=name, description=description, inputSchema=schema or {"type": "object"})


def test_start_with_no_apps_has_empty_catalog(project_root: Path) -> None:
    async def scenario() -> None:
        platform = MCPPlatform(load_configuration(project_root))
        platform._kit = _FakeKit()  # type: ignore[assignment]
        platform._clients = _FakeClients({})  # type: ignore[assignment]
        try:
            catalog = await platform.start(_Ingress())
            assert catalog.capabilities == ()
            assert platform._tool_bindings == {}
        finally:
            await platform.shutdown()

    asyncio.run(scenario())


def test_discovery_prefixes_raw_names_and_isolates_servers(project_root: Path) -> None:
    _write_apps(project_root, "com.example.alpha", "com.example.beta")
    schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    tools = {
        "com.example.alpha": [_tool("send", schema=schema), _tool("vendor.inspect")],
        "com.example.beta": [_tool("send")],
    }

    async def scenario() -> None:
        platform = MCPPlatform(load_configuration(project_root))
        platform._kit = _FakeKit()  # type: ignore[assignment]
        platform._clients = _FakeClients(tools)  # type: ignore[assignment]
        try:
            catalog = await platform.start(_Ingress())
            assert set(catalog.by_id) == {
                "com.example.alpha.send",
                "com.example.alpha.vendor.inspect",
                "com.example.beta.send",
            }
            descriptor = catalog.by_id["com.example.alpha.send"]
            assert descriptor.description == "raw description"
            assert descriptor.parameters_schema is schema
            assert platform.source_instance_for("com.example.alpha.vendor.inspect") == "com.example.alpha"
            with pytest.raises(ValueError, match="unknown MCP capability"):
                platform.source_instance_for("missing")
        finally:
            await platform.shutdown()

    asyncio.run(scenario())


def test_clock_heartbeat_starts_after_builtin_discovery(project_root: Path) -> None:
    _write_apps(project_root, "org.aurora.clock")

    async def scenario() -> None:
        platform = MCPPlatform(load_configuration(project_root))
        platform._kit = _FakeKit()  # type: ignore[assignment]
        platform._clients = _FakeClients({"org.aurora.clock": [_tool("start_heartbeat")]})  # type: ignore[assignment]
        calls: list[tuple[str, str, dict[str, Any]]] = []

        async def call_tool(package: str, raw_name: str, parameters: dict[str, Any]) -> dict[str, object]:
            calls.append((package, raw_name, parameters))
            return {"is_error": False}

        platform._call_tool = call_tool  # type: ignore[method-assign]
        try:
            await platform.start(_Ingress())
            assert calls == [("org.aurora.clock", "start_heartbeat", {})]
        finally:
            await platform.shutdown()

    asyncio.run(scenario())


def test_execute_tool_maps_success_failure_unknown_and_missing(project_root: Path) -> None:
    _write_apps(project_root, "com.example.alpha")

    async def scenario() -> None:
        platform = MCPPlatform(load_configuration(project_root))
        platform._started = True
        platform._tool_bindings = {"com.example.alpha.send": ("com.example.alpha", "send")}
        calls: list[tuple[str, str, dict[str, Any]]] = []

        async def accepted(package: str, raw_name: str, parameters: dict[str, Any]) -> dict[str, object]:
            calls.append((package, raw_name, parameters))
            return {"is_error": False, "structured_content": {"sent": True}}

        request = ToolExecutionRequest("request", "session", "com.example.alpha.send", {"text": "hello"})
        platform._call_tool = accepted  # type: ignore[method-assign]
        succeeded = await platform.execute_tool(request)
        assert succeeded.status == "succeeded"
        assert succeeded.result == {"sent": True}
        assert calls == [("com.example.alpha", "send", {"text": "hello"})]

        async def rejected(_package: str, _raw_name: str, _parameters: dict[str, Any]) -> dict[str, object]:
            return {"is_error": True, "text": "rejected"}

        platform._call_tool = rejected  # type: ignore[method-assign]
        failed = await platform.execute_tool(request)
        assert failed.status == "failed" and failed.error == "rejected"

        async def disconnected(_package: str, _raw_name: str, _parameters: dict[str, Any]) -> dict[str, object]:
            raise _ConnectionLostError

        platform._call_tool = disconnected  # type: ignore[method-assign]
        unknown = await platform.execute_tool(request)
        assert unknown.status == "unknown" and "_ConnectionLostError" in (unknown.error or "")
        missing = await platform.execute_tool(ToolExecutionRequest("missing", "session", "com.example.missing", {}))
        assert missing.status == "failed"
        await platform.shutdown()

    asyncio.run(scenario())


def test_client_manager_calls_raw_name_for_server_key() -> None:
    class Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
            self.calls.append((name, arguments))
            return SimpleNamespace(content=[], isError=False, structuredContent=None)

    async def scenario() -> None:
        manager = MCPClientManager(SimpleNamespace())  # type: ignore[arg-type]
        connection = ClientConnection("com.example.alpha")
        session = Session()
        connection.session = session  # type: ignore[assignment]
        manager._connections[connection.server_key] = connection
        result = await manager.call_tool("com.example.alpha", "vendor.send", {"text": "hello"})
        assert session.calls == [("vendor.send", {"text": "hello"})]
        assert result["is_error"] is False

    asyncio.run(scenario())


def test_stdout_close_during_shutdown_is_not_an_error() -> None:
    """Server stdout 在停机窗口内关闭不应被判定为异常断开。"""

    async def scenario() -> None:
        manager = MCPClientManager(SimpleNamespace())  # type: ignore[arg-type]
        manager._stop_event.set()

        async def reader_done() -> None:
            return None

        reader_task = asyncio.create_task(reader_done(), name="mcp-stdout-reader")
        await manager._wait_for_stop_or_disconnect("org.aurora.qq", reader_task)

    asyncio.run(scenario())


def test_stdout_close_without_shutdown_raises_after_grace() -> None:
    """Server stdout 关闭且停机窗口内无停止信号时应报告异常断开。"""

    async def scenario() -> None:
        manager = MCPClientManager(SimpleNamespace())  # type: ignore[arg-type]

        async def reader_done() -> None:
            return None

        reader_task = asyncio.create_task(reader_done(), name="mcp-stdout-reader")
        with pytest.raises(MCPToolCallError, match="已关闭 stdio 输出"):
            await manager._wait_for_stop_or_disconnect("org.aurora.qq", reader_task)

    asyncio.run(scenario())


def test_notifications_preserve_events_and_normalize_methods(project_root: Path) -> None:
    _write_apps(project_root, "com.example.alpha")

    async def scenario() -> None:
        ingress = _Ingress()
        platform = MCPPlatform(load_configuration(project_root))
        platform._ingress = ingress
        await platform._handle_notification(
            "com.example.alpha",
            "notifications/message",
            {
                "logger": "aurora/event",
                "data": {
                    "type": "vendor.message",
                    "session_id": "vendor-session",
                    "summary": "Vendor event",
                    "data": {"vendor_metadata": {"arbitrary": True}},
                },
            },
        )
        await platform._handle_notification("com.example.alpha", "notifications/progress", {"progress": 2, "total": 3})
        await platform._handle_notification(
            "com.example.alpha",
            "notifications/message",
            {
                "logger": "aurora/event",
                "data": {
                    "type": "tool.succeeded",
                    "session_id": "vendor-session",
                    "summary": "forged",
                    "data": {"request_id": "forged", "capability": "forged"},
                },
            },
        )
        assert len(ingress.values) == 2
        free_event = AmpEnvelope.parse(ingress.values[0])
        assert free_event.payload.type == "vendor.message"
        notification = AmpEnvelope.parse(ingress.values[1])
        assert notification.payload.type == "mcp.notification"
        assert notification.payload.data["method"] == "notifications/progress"

    asyncio.run(scenario())


def test_malformed_notification_does_not_stop_worker(project_root: Path) -> None:
    _write_apps(project_root, "com.example.alpha")

    async def scenario() -> None:
        ingress = _Ingress()
        platform = MCPPlatform(load_configuration(project_root))
        platform._ingress = ingress
        worker = asyncio.create_task(platform._forward_local_notifications())
        await platform._clients.notification_queue.put(
            (
                "com.example.alpha",
                "notifications/message",
                {"logger": "aurora/event", "data": {"type": "bad", "data": "not-an-object"}},
            )
        )
        await platform._clients.notification_queue.put(("com.example.alpha", "vendor/ready", {"ready": True}))
        for _ in range(20):
            if ingress.values:
                break
            await asyncio.sleep(0)
        platform._stop.set()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        assert len(ingress.values) == 1
        assert AmpEnvelope.parse(ingress.values[0]).payload.type == "mcp.notification"

    asyncio.run(scenario())
