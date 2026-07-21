from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.contracts.amp import AmpEnvelope, new_amp
from src.contracts.configuration import load_configuration
from src.contracts.model import ModelContinuation, ModelResult, ModelUsage, ToolCall
from src.localhost.ports import ToolExecutionRequest, ToolExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.mcp import MCPPlatform
from src.platform.mcp.client_manager import ClientConnection, MCPClientManager

EXPECTED_NOTIFICATIONS = 2


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


def test_start_with_no_configured_apps_has_empty_catalog(project_root: Path) -> None:
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


def test_clock_heartbeat_starts_after_builtin_tool_discovery(project_root: Path) -> None:
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


def test_discovery_prefixes_every_raw_name_and_isolates_servers(project_root: Path) -> None:
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
            assert platform._tool_bindings["com.example.alpha.vendor.inspect"] == (
                "com.example.alpha",
                "vendor.inspect",
            )
            assert platform.source_instance_for("com.example.alpha.vendor.inspect") == "com.example.alpha"
            with pytest.raises(ValueError, match="unknown MCP capability"):
                platform.source_instance_for("missing")
        finally:
            await platform.shutdown()

    asyncio.run(scenario())


def test_agent_continues_across_tools_from_two_mcp_packages(project_root: Path) -> None:
    _write_apps(project_root, "com.example.alpha", "org.vendor.beta")
    tools = {
        "com.example.alpha": [_tool("lookup")],
        "org.vendor.beta": [_tool("vendor.send")],
    }

    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root, tool_bindings=None)
        platform = MCPPlatform(load_configuration(project_root))
        platform._kit = _FakeKit()  # type: ignore[assignment]
        platform._clients = _FakeClients(tools)  # type: ignore[assignment]
        calls: list[tuple[str, str, dict[str, Any]]] = []

        async def call_tool(package: str, raw_name: str, parameters: dict[str, Any]) -> dict[str, object]:
            calls.append((package, raw_name, parameters))
            return {"is_error": False, "structured_content": {"ok": True}}

        try:
            catalog = await platform.start(runtime)
            platform._call_tool = call_tool  # type: ignore[method-assign]
            runtime.bind_tool_executors(
                tuple(
                    ToolExecutorBinding(
                        descriptor,
                        platform,
                        "platform.mcp",
                        platform.source_instance_for(descriptor.id),
                    )
                    for descriptor in catalog.capabilities
                )
            )
            await runtime.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="session",
                    summary="lookup then send",
                    data={"text": "lookup then send"},
                    source_app="test",
                    source_instance="test",
                ).to_dict()
            )
            await runtime.kernel.pump()
            first_model = (await runtime.kernel.claim_model_requests(1))[0]
            continuation = ModelContinuation("test", "chat_completions")
            first_result = ModelResult(
                "test",
                frozenset({"chat", "tools"}),
                "normalized",
                "",
                None,
                ModelUsage(),
                0,
                tool_calls=(ToolCall("first", "com.example.alpha.lookup", {"query": "Aurora"}),),
                finish_reason="tool_calls",
                continuation=continuation,
            )
            await runtime.kernel.complete_model(first_model, first_result.to_dict(), None)
            await runtime.kernel.pump()
            await runtime._tool_dispatcher.dispatch_pending_tools()
            await runtime.kernel.pump()

            second_model = (await runtime.kernel.claim_model_requests(1))[0]
            second_result = ModelResult(
                "test",
                frozenset({"chat", "tools"}),
                "normalized",
                "",
                None,
                ModelUsage(),
                0,
                tool_calls=(
                    ToolCall(
                        "second",
                        "org.vendor.beta.vendor.send",
                        {"text": "result", "complete_task": True},
                    ),
                ),
                finish_reason="tool_calls",
                continuation=continuation,
            )
            await runtime.kernel.complete_model(second_model, second_result.to_dict(), None)
            await runtime.kernel.pump()
            await runtime._tool_dispatcher.dispatch_pending_tools()

            assert calls == [
                ("com.example.alpha", "lookup", {"query": "Aurora"}),
                ("org.vendor.beta", "vendor.send", {"text": "result"}),
            ]
            assert runtime.kernel.tasks()[0].status.value == "COMPLETED"
        finally:
            await platform.shutdown()
            await runtime.shutdown()

    asyncio.run(scenario())


def test_clock_raw_tools_are_discovered_and_called_with_package_prefix(project_root: Path) -> None:
    app_directory = (Path(__file__).parents[1] / "src" / "apps" / "aurora-app-clock").as_posix()
    (project_root / "config" / "apps.toml").write_text(
        f"""[[app]]
package = "org.aurora.clock"
enabled = true
transport = "stdio"
working_dir = "{app_directory}"
command = ["uv", "run", "--no-sync", "python", "mcp_server.py"]
timeout_seconds = 30
""",
        encoding="utf-8",
    )

    async def scenario() -> None:
        platform = MCPPlatform(load_configuration(project_root), terminal_logs=False)
        try:
            catalog = await platform.start(_Ingress())
            assert "org.aurora.clock.get_current_time" in catalog.by_id
            assert "org.aurora.clock.sleep" in catalog.by_id
            raw_tools = platform._clients.list_all_tools()["org.aurora.clock"]
            assert all(tool.description for tool in raw_tools)
            assert platform._tool_bindings["org.aurora.clock.get_current_time"] == (
                "org.aurora.clock",
                "get_current_time",
            )
            outcome = await platform.execute_tool(
                ToolExecutionRequest("clock-request", "clock-session", "org.aurora.clock.get_current_time", {})
            )
            assert outcome.status == "succeeded"
            rest = await platform.execute_tool(
                ToolExecutionRequest("sleep-request", "clock-session", "org.aurora.clock.sleep", {"seconds": 60})
            )
            assert rest.status == "succeeded"
        finally:
            await platform.shutdown()

    asyncio.run(scenario())


def test_execute_tool_calls_mapped_raw_name_with_only_parameters(project_root: Path) -> None:
    _write_apps(project_root, "com.example.alpha")

    async def scenario() -> None:
        platform = MCPPlatform(load_configuration(project_root))
        platform._started = True
        platform._tool_bindings = {"com.example.alpha.vendor.send": ("com.example.alpha", "vendor.send")}
        calls: list[tuple[str, str, dict[str, Any]]] = []

        async def call_tool(package: str, raw_name: str, parameters: dict[str, Any]) -> dict[str, object]:
            calls.append((package, raw_name, parameters))
            return {"is_error": False, "structured_content": {"sent": True}}

        platform._call_tool = call_tool  # type: ignore[method-assign]
        request = ToolExecutionRequest(
            "request-1",
            "session-1",
            "com.example.alpha.vendor.send",
            {"text": "hello"},
        )
        outcome = await platform.execute_tool(request)
        assert outcome.status == "succeeded"
        assert calls == [("com.example.alpha", "vendor.send", {"text": "hello"})]
        await platform.shutdown()

    asyncio.run(scenario())


def test_execute_tool_maps_is_error_to_failed_and_exception_to_unknown(project_root: Path) -> None:
    _write_apps(project_root, "com.example.alpha")

    async def scenario() -> None:
        platform = MCPPlatform(load_configuration(project_root))
        platform._started = True
        platform._tool_bindings = {"com.example.alpha.send": ("com.example.alpha", "send")}

        async def rejected(_package: str, _raw_name: str, _parameters: dict[str, Any]) -> dict[str, object]:
            return {"is_error": True, "text": "rejected"}

        platform._call_tool = rejected  # type: ignore[method-assign]
        request = ToolExecutionRequest("request", "session", "com.example.alpha.send", {})
        failed = await platform.execute_tool(request)
        assert failed.status == "failed" and failed.error == "rejected"

        async def disconnected(_package: str, _raw_name: str, _parameters: dict[str, Any]) -> dict[str, object]:
            raise _ConnectionLostError

        platform._call_tool = disconnected  # type: ignore[method-assign]
        unknown = await platform.execute_tool(request)
        assert unknown.status == "unknown" and "_ConnectionLostError" in (unknown.error or "")
        await platform.shutdown()

    asyncio.run(scenario())


def test_client_manager_calls_raw_name_for_explicit_server_key() -> None:
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
        await manager.call_tool("com.example.alpha", "vendor.send", {"text": "hello"})
        assert session.calls == [("vendor.send", {"text": "hello"})]

    asyncio.run(scenario())


def test_notifications_preserve_free_event_and_normalize_other_methods(project_root: Path) -> None:
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
                    "data": {"vendor_metadata": {"arbitrary": True}, "request_id": "not-a-receipt"},
                },
            },
        )
        await platform._handle_notification(
            "com.example.alpha",
            "notifications/progress",
            {"progress": 2, "total": 3},
        )
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
        assert len(ingress.values) == EXPECTED_NOTIFICATIONS
        free_event = AmpEnvelope.parse(ingress.values[0])
        assert free_event.payload.type == "vendor.message"
        assert free_event.payload.session_id == "vendor-session"
        assert free_event.payload.data["vendor_metadata"] == {"arbitrary": True}
        assert free_event.header.source["app"] == "com.example.alpha"
        notification = AmpEnvelope.parse(ingress.values[1])
        assert notification.payload.type == "mcp.notification"
        assert notification.payload.data == {
            "method": "notifications/progress",
            "params": {"progress": 2, "total": 3},
        }

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
