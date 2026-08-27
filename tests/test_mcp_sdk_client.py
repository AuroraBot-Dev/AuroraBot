from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx2
import pytest
from mcp.client.client import Client
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters
from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.server.extension import Extension
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CONNECTION_CLOSED,
    INTERNAL_ERROR,
    REQUEST_TIMEOUT,
    CallToolResult,
    ImageContent,
    InputRequiredResult,
    Notification,
    NotificationParams,
    ServerNotification,
    TextContent,
)
from pydantic import Field

from src.mcp import (
    TOOL_CONTRACT_EXTENSION,
    WORLD_EVENT_NOTIFICATION,
    WORLD_EVENTS_EXTENSION,
    McpAppSpec,
    McpCallRejectedError,
    McpCallUnknownError,
    McpEventMode,
    McpInboundEvent,
    McpTransport,
    SdkMcpClientFactory,
)

if TYPE_CHECKING:
    from pathlib import Path

_TIMEOUT_SECONDS = 7.0


class _ToolContractServerExtension(Extension):
    identifier = TOOL_CONTRACT_EXTENSION

    def __init__(self, settings: dict[str, Any]) -> None:
        self._settings = dict(settings)

    def settings(self) -> dict[str, Any]:
        return dict(self._settings)


class _WorldEventsServerExtension(Extension):
    identifier = WORLD_EVENTS_EXTENSION

    def __init__(self, settings: dict[str, Any]) -> None:
        self._settings = dict(settings)

    def settings(self) -> dict[str, Any]:
        return dict(self._settings)


class _EventParams(NotificationParams):
    event_id: str = Field(alias="event_id")
    scope: str
    kind: str
    occurred_at: datetime = Field(alias="occurred_at")
    summary: str
    data: dict[str, Any]


class _EventNotification(Notification[_EventParams, Literal["notifications/org.aurorabot/world-events/event"]]):
    method: Literal["notifications/org.aurorabot/world-events/event"] = WORLD_EVENT_NOTIFICATION
    params: _EventParams


class _EmitEventMiddleware(ServerMiddleware[Any]):
    async def __call__(
        self,
        context: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        result = await call_next(context)
        if context.method == "tools/list":
            notification = _EventNotification(
                params=_EventParams(
                    event_id="gate-event",
                    scope="qq:group:1",
                    kind="qq.message.group",
                    occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
                    summary="门闩测试",
                    data={"message_id": "1"},
                )
            )
            await context.session.send_notification(
                cast("ServerNotification", notification),
                related_request_id=context.request_id,
            )
        return result


def _server() -> MCPServer:
    server = MCPServer("aurora-sdk-test")

    @server.tool(description="回显文本")
    async def echo(text: str) -> str:
        return f"echo:{text}"

    return server


def _contract_server(settings: dict[str, Any]) -> MCPServer:
    server = MCPServer(
        "aurora-contract-test",
        extensions=(_ToolContractServerExtension(settings),),
    )

    @server.tool(
        description="发送文本",
        meta={
            TOOL_CONTRACT_EXTENSION: {
                "observe": ["qq:group:{group_id}"],
                "publish": ["qq:group:{group_id}"],
            }
        },
    )
    async def send(group_id: int, text: str) -> str:
        return f"{group_id}:{text}"

    return server


def _event_server(settings: dict[str, Any]) -> MCPServer:
    return MCPServer(
        "aurora-event-test",
        extensions=(_WorldEventsServerExtension(settings),),
        middleware=(_EmitEventMiddleware(),),
    )


def _stdio_spec(tmp_path: Path, *, terminal_logs: bool = False) -> McpAppSpec:
    return McpAppSpec(
        package="test.echo",
        enabled=True,
        transport=McpTransport.STDIO,
        timeout_seconds=_TIMEOUT_SECONDS,
        terminal_logs=terminal_logs,
        command=("python", "-m", "test_server"),
        working_dir=tmp_path,
        environment={"AURORA_TEST_TOKEN": "test-value"},
    )


def _event_spec(tmp_path: Path) -> McpAppSpec:
    return McpAppSpec(
        package="test.events",
        enabled=True,
        transport=McpTransport.STDIO,
        timeout_seconds=_TIMEOUT_SECONDS,
        terminal_logs=False,
        event_mode=McpEventMode.WORLD_EVENTS,
        command=("python", "-m", "test_server"),
        working_dir=tmp_path,
    )


def _http_spec() -> McpAppSpec:
    return McpAppSpec(
        package="test.remote",
        enabled=True,
        transport=McpTransport.STREAMABLE_HTTP,
        timeout_seconds=_TIMEOUT_SECONDS,
        terminal_logs=False,
        url="https://mcp.example.test/rpc",
        auth_token="test-secret",
    )


async def _ignore_event(_event: McpInboundEvent) -> None:
    return None


def _route_stdio_to_server(monkeypatch: pytest.MonkeyPatch, server: MCPServer) -> None:
    def fake_stdio_client(
        _parameters: StdioServerParameters,
        *,
        errlog: object,
    ) -> MCPServer:
        _ = errlog
        return server

    monkeypatch.setattr("src.mcp.client.stdio_client", fake_stdio_client)


def test_official_sdk_v2_in_memory_negotiates_discovers_and_calls() -> None:
    async def scenario() -> None:
        async with Client(_server(), mode="auto", cache=None, input_required_max_rounds=0) as client:
            assert client.protocol_version == "2026-07-28"

            catalog = await client.list_tools(cache_mode="bypass")
            assert [tool.name for tool in catalog.tools] == ["echo"]
            assert catalog.tools[0].input_schema["type"] == "object"
            assert catalog.tools[0].input_schema["required"] == ["text"]

            result = await client.session.call_tool(
                "echo",
                {"text": "你好"},
                read_timeout_seconds=_TIMEOUT_SECONDS,
                allow_input_required=True,
            )
            assert isinstance(result, CallToolResult)
            assert result.is_error is False
            assert result.structured_content == {"result": "echo:你好"}
            assert result.content == [TextContent(text="echo:你好")]

    asyncio.run(scenario())


def test_sdk_adapter_uses_frozen_client_options_and_projects_official_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    _route_stdio_to_server(monkeypatch, server)
    captured: dict[str, object] = {}
    official_client = Client

    def recording_client(server_or_transport: object, **options: object) -> Client:
        captured.update(options)
        return official_client(server_or_transport, **options)  # type: ignore[arg-type]

    monkeypatch.setattr("src.mcp.client.Client", recording_client)

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_stdio_spec(tmp_path), _ignore_event)
        assert client.protocol_version == "2026-07-28"

        page = await client.list_tools()
        assert page.next_cursor is None
        assert [(tool.name, tool.description) for tool in page.tools] == [("echo", "回显文本")]
        assert page.tools[0].input_schema["required"] == ("text",)

        result = await client.call_tool("echo", {"text": "Aurora"}, _TIMEOUT_SECONDS)
        assert result.is_error is False
        assert result.structured_content == {"result": "echo:Aurora"}
        assert [(block.kind, block.text) for block in result.content] == [("text", "echo:Aurora")]
        await client.close()
        assert client.connected is False

    asyncio.run(scenario())

    assert captured["mode"] == "auto"
    assert captured["cache"] is None
    assert captured["read_timeout_seconds"] == _TIMEOUT_SECONDS
    assert captured["input_required_max_rounds"] == 0
    assert callable(captured["message_handler"])
    assert captured["logging_callback"] is None
    extensions = captured["extensions"]
    assert isinstance(extensions, tuple)
    assert [extension.identifier for extension in extensions] == [TOOL_CONTRACT_EXTENSION]


def test_stdio_factory_preserves_command_whitelist_cwd_and_log_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    server = _server()

    def fake_stdio_client(parameters: StdioServerParameters, *, errlog: object) -> MCPServer:
        captured["parameters"] = parameters
        captured["errlog"] = errlog
        return server

    monkeypatch.setattr("src.mcp.client.stdio_client", fake_stdio_client)

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_stdio_spec(tmp_path), _ignore_event)
        await client.close()

    asyncio.run(scenario())

    parameters = captured["parameters"]
    assert isinstance(parameters, StdioServerParameters)
    assert parameters.command == "python"
    assert parameters.args == ["-m", "test_server"]
    assert parameters.cwd == tmp_path
    assert parameters.env == {"AURORA_TEST_TOKEN": "test-value"}
    assert captured["errlog"] == subprocess.DEVNULL


def test_strict_v1_tool_contract_projects_tool_metadata_and_unknown_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_stdio_to_server(monkeypatch, _contract_server({"version": 1}))
    results = iter(
        (
            CallToolResult(
                content=[TextContent(text="下游结果无法确认")],
                is_error=False,
                _meta={TOOL_CONTRACT_EXTENSION: {"status": "unknown"}},
            ),
            CallToolResult(content=[TextContent(text="明确拒绝")], is_error=True),
        )
    )

    async def fake_call_tool(
        _session: object,
        _name: str,
        _arguments: dict[str, object],
        *,
        read_timeout_seconds: float,
        allow_input_required: bool,
    ) -> CallToolResult:
        _ = read_timeout_seconds, allow_input_required
        return next(results)

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_stdio_spec(tmp_path), _ignore_event)
        page = await client.list_tools()
        assert page.tools[0].tool_contract == {
            "observe": ("qq:group:{group_id}",),
            "publish": ("qq:group:{group_id}",),
        }

        monkeypatch.setattr(ClientSession, "call_tool", fake_call_tool)
        unknown = await client.call_tool("send", {"group_id": 1, "text": "hello"}, _TIMEOUT_SECONDS)
        failed = await client.call_tool("send", {"group_id": 1, "text": "hello"}, _TIMEOUT_SECONDS)
        assert unknown.effect_unknown is True
        assert failed.is_error is True and failed.effect_unknown is False
        await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "settings",
    (
        {"version": "1"},
        {"version": True},
        {"version": 2},
        {"version": 1, "extra": True},
    ),
)
def test_tool_contract_metadata_requires_exact_server_v1_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: dict[str, Any],
) -> None:
    _route_stdio_to_server(monkeypatch, _contract_server(settings))

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_stdio_spec(tmp_path), _ignore_event)
        page = await client.list_tools()
        assert page.tools[0].tool_contract is None
        await client.close()

    asyncio.run(scenario())


def test_strict_v1_world_events_are_delivered_only_while_gate_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_stdio_to_server(monkeypatch, _event_server({"version": 1}))
    received: list[McpInboundEvent] = []

    async def receive(event: McpInboundEvent) -> None:
        received.append(event)

    async def settle() -> None:
        for _ in range(3):
            await asyncio.sleep(0)

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_event_spec(tmp_path), receive)

        await client.list_tools()
        await settle()
        assert received == []

        client.activate_events()
        await client.list_tools()
        await settle()
        assert [(event.event_id, event.scope, event.kind) for event in received] == [
            ("gate-event", "qq:group:1", "qq.message.group")
        ]

        client.deactivate_events()
        await client.list_tools()
        await settle()
        assert len(received) == 1
        await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "settings",
    (
        {"version": "1"},
        {"version": True},
        {"version": 2},
        {"version": 1, "extra": True},
    ),
)
def test_world_events_require_exact_server_v1_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: dict[str, Any],
) -> None:
    _route_stdio_to_server(monkeypatch, _event_server(settings))

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="未严格协商事件扩展"):
            await SdkMcpClientFactory().open(_event_spec(tmp_path), _ignore_event)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "contract_meta",
    (
        {},
        {"status": "failed"},
        {"status": "unknown", "extra": True},
        ["unknown"],
    ),
)
def test_negotiated_tool_contract_rejects_malformed_result_metadata_as_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contract_meta: object,
) -> None:
    _route_stdio_to_server(monkeypatch, _contract_server({"version": 1}))

    async def fake_call_tool(
        _session: object,
        _name: str,
        _arguments: dict[str, object],
        *,
        read_timeout_seconds: float,
        allow_input_required: bool,
    ) -> CallToolResult:
        _ = read_timeout_seconds, allow_input_required
        return CallToolResult(
            content=[TextContent(text="malformed")],
            is_error=True,
            _meta={TOOL_CONTRACT_EXTENSION: contract_meta},
        )

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_stdio_spec(tmp_path), _ignore_event)
        monkeypatch.setattr(ClientSession, "call_tool", fake_call_tool)
        with pytest.raises(McpCallUnknownError, match="结果元数据非法"):
            await client.call_tool("send", {"group_id": 1, "text": "hello"}, _TIMEOUT_SECONDS)
        await client.close()

    asyncio.run(scenario())


@dataclass(slots=True)
class _FakeHttpClient:
    closed: bool = False

    async def __aenter__(self) -> _FakeHttpClient:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        self.closed = True


def test_http_factory_disables_redirects_uses_one_timeout_and_releases_client(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _server()
    fake_http_client = _FakeHttpClient()
    captured: dict[str, object] = {}

    def make_http_client(**options: object) -> _FakeHttpClient:
        captured["http_options"] = options
        return fake_http_client

    def fake_streamable_http_client(url: str, *, http_client: object) -> MCPServer:
        captured["url"] = url
        captured["http_client"] = http_client
        return server

    monkeypatch.setattr("src.mcp.client.httpx2.AsyncClient", make_http_client)
    monkeypatch.setattr("src.mcp.client.streamable_http_client", fake_streamable_http_client)

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_http_spec(), _ignore_event)
        assert fake_http_client.closed is False
        await client.close()

    asyncio.run(scenario())

    options = captured["http_options"]
    assert isinstance(options, dict)
    assert options["headers"] == {"Authorization": "Bearer test-secret"}
    assert options["follow_redirects"] is False
    timeout = options["timeout"]
    assert isinstance(timeout, httpx2.Timeout)
    assert timeout.connect == _TIMEOUT_SECONDS
    assert timeout.read == _TIMEOUT_SECONDS
    assert timeout.write == _TIMEOUT_SECONDS
    assert timeout.pool == _TIMEOUT_SECONDS
    assert captured["url"] == "https://mcp.example.test/rpc"
    assert captured["http_client"] is fake_http_client
    assert fake_http_client.closed is True


def test_sdk_adapter_maps_call_arguments_text_and_nontext_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_stdio_to_server(monkeypatch, _server())
    captured: dict[str, object] = {}

    async def fake_call_tool(
        _session: object,
        name: str,
        arguments: dict[str, object],
        *,
        read_timeout_seconds: float,
        allow_input_required: bool,
    ) -> CallToolResult:
        captured.update(
            name=name,
            arguments=arguments,
            read_timeout_seconds=read_timeout_seconds,
            allow_input_required=allow_input_required,
        )
        return CallToolResult(
            structured_content={"answer": 42},
            content=[TextContent(text="完成"), ImageContent(data="AA==", mime_type="image/png")],
        )

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_stdio_spec(tmp_path), _ignore_event)
        monkeypatch.setattr(ClientSession, "call_tool", fake_call_tool)
        result = await client.call_tool("echo", {"text": "请求"}, _TIMEOUT_SECONDS)
        assert result.structured_content == {"answer": 42}
        assert [(block.kind, block.text) for block in result.content] == [
            ("text", "完成"),
            ("image", None),
        ]
        await client.close()

    asyncio.run(scenario())

    assert captured == {
        "name": "echo",
        "arguments": {"text": "请求"},
        "read_timeout_seconds": _TIMEOUT_SECONDS,
        "allow_input_required": True,
    }


@pytest.mark.parametrize(
    ("error", "expected_type", "message", "expected_connected"),
    [
        (MCPError(CONNECTION_CLOSED, "closed"), McpCallUnknownError, "连接已中断", False),
        (MCPError(REQUEST_TIMEOUT, "timeout"), McpCallUnknownError, "调用超时", True),
        (MCPError(INTERNAL_ERROR, "internal"), McpCallUnknownError, "无法确认调用效果", True),
        (MCPError(-32602, "invalid"), McpCallRejectedError, "Server 明确拒绝调用", True),
        (RuntimeError("broken"), McpCallUnknownError, "结果无法确认", True),
    ],
)
def test_sdk_adapter_classifies_call_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_type: type[Exception],
    message: str,
    expected_connected: bool,
) -> None:
    _route_stdio_to_server(monkeypatch, _server())

    async def fail_call_tool(
        _session: object,
        _name: str,
        _arguments: dict[str, object],
        *,
        read_timeout_seconds: float,
        allow_input_required: bool,
    ) -> CallToolResult:
        _ = read_timeout_seconds, allow_input_required
        raise error

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_stdio_spec(tmp_path), _ignore_event)
        monkeypatch.setattr(ClientSession, "call_tool", fail_call_tool)
        with pytest.raises(expected_type) as exc_info:
            await client.call_tool("echo", {"text": "请求"}, _TIMEOUT_SECONDS)
        assert message in str(exc_info.value)
        assert client.connected is expected_connected
        if not expected_connected:
            with pytest.raises(McpCallRejectedError, match="调用未发送"):
                await client.call_tool("echo", {"text": "不会发送"}, _TIMEOUT_SECONDS)
        await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (InputRequiredResult(request_state="opaque-state"), "input_required"),
        (object(), "未启用的扩展结果"),
    ],
)
def test_sdk_adapter_classifies_unhandled_result_shapes_as_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: object,
    message: str,
) -> None:
    _route_stdio_to_server(monkeypatch, _server())

    async def return_result(
        _session: object,
        _name: str,
        _arguments: dict[str, object],
        *,
        read_timeout_seconds: float,
        allow_input_required: bool,
    ) -> object:
        _ = read_timeout_seconds, allow_input_required
        return result

    async def scenario() -> None:
        client = await SdkMcpClientFactory().open(_stdio_spec(tmp_path), _ignore_event)
        monkeypatch.setattr(ClientSession, "call_tool", return_result)
        with pytest.raises(McpCallUnknownError, match=message):
            await client.call_tool("echo", {"text": "请求"}, _TIMEOUT_SECONDS)
        await client.close()

    asyncio.run(scenario())
