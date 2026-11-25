"""创建 MCP 传输并进入 SDK 会话；所有上下文由连接所有者的同一任务退出。"""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from .credentials import resolve_values
from .errors import MCPClientError
from .negotiation import Negotiation, confirm
from .stdio import parameters, stdio_transport


class _HTTPBoundary:
    """只观察协商报文；拒绝鉴权失败与重定向，避免 SDK 把 HTTP 故障当作版本回退。"""

    def __init__(self, state: Negotiation) -> None:
        self.state = state
        self._get_opened = False

    async def request(self, request: httpx2.Request) -> None:
        if self.state.failure:
            raise MCPClientError(self.state.failure)
        if request.method == "GET":
            if "last-event-id" in request.headers or self._get_opened:
                raise MCPClientError("reconnect_disabled")
            self._get_opened = True
        if self.state.active and request.method == "POST":
            method = json.loads(request.content).get("method")
            attempt = self.state.request(method)
            if attempt is not None:
                request.extensions["aurora_mcp_attempt"] = attempt

    async def response(self, response: httpx2.Response) -> None:
        attempt = response.request.extensions.get("aurora_mcp_attempt")
        if attempt is not None:
            attempt["http_status"] = response.status_code
        if response.status_code in (401, 403):
            self.state.fail("authentication_failed")
        if response.status_code >= 500:
            self.state.fail("http_failed")
        if 300 <= response.status_code < 400:
            self.state.fail("redirect_rejected")
        if (
            attempt is not None
            and response.status_code == 200
            and not response.headers.get("content-type", "")
            .lower()
            .startswith(("application/json", "text/event-stream"))
        ):
            self.state.fail("invalid_protocol_response")
        if attempt is not None and response.headers.get("content-type", "").lower().startswith("application/json"):
            try:
                payload = json.loads(await response.aread())
            except (ValueError, UnicodeError):
                self.state.fail("invalid_protocol_response")
                return
            self.state.response(attempt, payload)


@asynccontextmanager
async def open_client(
    config: dict, resolve_env: Callable[[str], str | None], state: Negotiation, *, workspace_root: Path | None = None
) -> AsyncIterator[Client]:
    """两种传输共用 SDK 会话与协商；凭证仅存在于本次运行的资源内。"""
    request_timeout = max(config["timeout"][key] for key in ("startup", "catalog", "execution"))
    async with Client(
        _transport(config, resolve_env, state, workspace_root),
        mode=config["protocol"],
        read_timeout_seconds=request_timeout,
        input_required_max_rounds=0,
        cache=None,
    ) as client:
        await confirm(client, config, state)
        yield client


@asynccontextmanager
async def _transport(config, resolve_env, state, workspace_root):
    if config["type"] == "local":
        server = parameters(config, workspace_root, resolve_env)
        async with stdio_transport(server, state) as streams:
            yield streams
        return
    try:
        headers = resolve_values(config.get("headers", {}), resolve_env, headers=True)
    except ValueError as error:
        raise MCPClientError(
            "credential_unavailable", location=f"servers.{config['connection_id']}.headers.{error}"
        ) from None
    request_timeout = max(config["timeout"][key] for key in ("startup", "catalog", "execution"))
    boundary = _HTTPBoundary(state)
    async with (
        httpx2.AsyncClient(
            headers=headers,
            timeout=httpx2.Timeout(request_timeout),
            follow_redirects=False,
            trust_env=False,
            event_hooks={"request": [boundary.request], "response": [boundary.response]},
        ) as http,
        streamable_http_client(config["url"], http_client=http) as streams,
    ):
        yield streams
