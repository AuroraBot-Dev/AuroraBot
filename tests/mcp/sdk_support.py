"""该能力测试共用的离线替身与场景构造。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.server.extension import Extension
from mcp.types import (
    Notification,
    NotificationParams,
    ServerNotification,
)
from pydantic import Field

from aurora_bot.mcp import (
    TOOL_CONTRACT_EXTENSION,
    WORLD_EVENT_NOTIFICATION,
    WORLD_EVENTS_EXTENSION,
    McpAppSpec,
    McpEventMode,
    McpInboundEvent,
    McpTransport,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from mcp.client.stdio import StdioServerParameters


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

    monkeypatch.setattr("aurora_bot.mcp.client.stdio_client", fake_stdio_client)


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
