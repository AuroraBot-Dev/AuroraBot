"""使用真实 SDK 和模拟 HTTP 验证协商、错误分类、预算及无动作重发。"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import cast

import httpx2
import pytest
from aurora_adapter.mcp import CLIENT_STATUS, CONFIG_STATE, MCPClientError, MCPClients, transports
from aurora_adapter.mcp import clients as clients_module
from aurora_adapter.mcp.configuration import PROTOCOL_VERSION
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import install_lifecycle_slots
from mcp.shared.exceptions import MCPError
from mcp.types import DiscoverResult, Implementation, InitializeResult, ServerCapabilities, ToolsCapability

LEGACY = "2025-11-25"
SECRET = "do-not-log-remote-payload"


@pytest.mark.parametrize("cancel", [False, True])
def test_auto_fallback_shares_budget_and_external_cancel_is_not_retry(host, startup_timeouts, cancel):
    create, observed = host

    async def scenario():
        entered, finished = asyncio.Event(), asyncio.Event()
        deadline = None

        async def first(method):
            nonlocal deadline
            assert len(startup_timeouts) == 1
            deadline = startup_timeouts[0].when()
            return {"code": -32603, "message": SECRET}

        async def stuck(method):
            assert len(startup_timeouts) == 1
            assert startup_timeouts[0].when() == deadline
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        owner, status = create("auto", [first, stuck], startup=10)
        task = asyncio.create_task(owner.prepare())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                startup_timeouts[0].reschedule(asyncio.get_running_loop().time())
                with pytest.raises(MCPClientError, match="connect_timeout"):
                    await task
        finally:
            await owner.clean()
        assert observed == ["server/discover", "initialize"]
        assert finished.is_set()
        assert status()["negotiated_protocol"] is None

    asyncio.run(scenario())


@pytest.fixture
def startup_timeouts(monkeypatch):
    """保留真实超时取消语义，由握手事件决定预算到期时刻。"""
    timeouts = []

    def timeout(delay):
        if not timeouts:
            assert delay == 10
        timer = asyncio.timeout(delay)
        timeouts.append(timer)
        return timer

    monkeypatch.setattr(clients_module, "asyncio", SimpleNamespace(**(vars(asyncio) | {"timeout": timeout})))
    return timeouts


@pytest.mark.parametrize("resume", [False, True])
def test_http_boundary_blocks_network_reconnect_and_sse_resumption(resume):
    from aurora_adapter.mcp.negotiation import Negotiation

    async def scenario():
        seen = []

        async def respond(request):
            seen.append(request.method)
            return httpx2.Response(405)

        boundary = transports._HTTPBoundary(Negotiation("legacy"))
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(respond), event_hooks={"request": [boundary.request]}
        ) as http:
            if not resume:
                await http.get("http://localhost/mcp")
            with pytest.raises(MCPClientError, match="reconnect_disabled"):
                await http.get("http://localhost/mcp", headers={"Last-Event-ID": "opaque"} if resume else {})
            assert seen == ([] if resume else ["GET"])

    asyncio.run(scenario())


def discovery(versions=None):
    return DiscoverResult(
        supported_versions=versions or [PROTOCOL_VERSION], capabilities=ServerCapabilities(tools=ToolsCapability())
    ).model_dump(by_alias=True, exclude_none=True)


def initialize(version=LEGACY, *, tools=True):
    return InitializeResult(
        protocol_version=version,
        capabilities=ServerCapabilities(tools=ToolsCapability()) if tools else ServerCapabilities(),
        server_info=Implementation(name="test", version="1"),
    ).model_dump(by_alias=True, exclude_none=True)


@pytest.fixture
def host(monkeypatch):
    observations, clients, contexts = [], [], []
    original = httpx2.AsyncClient

    def create(mode, replies, *, startup=1, required=None):
        async def respond(request):
            if request.method != "POST":
                return httpx2.Response(405)
            data = json.loads(request.content)
            method = data["method"]
            observations.append(method)
            if method.startswith("notifications/"):
                return httpx2.Response(202)
            reply = replies.pop(0)
            if callable(reply):
                reply = await cast(Callable[[str], Awaitable[object]], reply)(method)
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, httpx2.Response):
                return reply
            result = {"jsonrpc": "2.0", "id": data["id"]}
            result["error" if isinstance(reply, dict) and "code" in reply else "result"] = reply
            return httpx2.Response(200, json=result)

        def http(**kwargs):
            client = original(**kwargs, transport=httpx2.MockTransport(respond))
            clients.append(client)
            return client

        monkeypatch.setattr(transports.httpx2, "AsyncClient", http)
        registry = bootstrap()
        install_lifecycle_slots(registry)
        register_plugins(registry, load_plugins(enabled=["aurora_config", "aurora_adapter.mcp"]))
        ctx, hooks = Context(registry), HookConnections(registry)
        contexts.append(ctx)
        ctx.set(
            CONFIG_STATE,
            {
                "schema_version": 2,
                "servers": {
                    "test": {
                        "type": "remote",
                        "url": "http://localhost/mcp",
                        "protocol": mode,
                        "required_capabilities": required or [],
                        "timeout": {"startup": startup},
                    }
                },
            },
        )
        owner = MCPClients(ctx, hooks)
        owner.configure()

        def status():
            return cast(dict, ctx.get(CLIENT_STATUS, location={"owner": owner.instance_id, "connection_id": "test"}))

        return owner, status

    yield create, observations
    assert all(client.is_closed for client in clients)
    for ctx in contexts:
        assert SECRET not in repr(ctx.snapshot())
        ctx.close()


@pytest.mark.parametrize(
    "mode,replies,methods,version",
    [
        ("legacy", [initialize()], ["initialize", "notifications/initialized"], LEGACY),
        ("auto", [discovery()], ["server/discover"], PROTOCOL_VERSION),
        (PROTOCOL_VERSION, [discovery()], ["server/discover"], PROTOCOL_VERSION),
        (
            "auto",
            [{"code": -32601, "message": SECRET}, initialize()],
            ["server/discover", "initialize", "notifications/initialized"],
            LEGACY,
        ),
        (
            "auto",
            [{"code": -32603, "message": SECRET}, initialize()],
            ["server/discover", "initialize", "notifications/initialized"],
            LEGACY,
        ),
        (
            "auto",
            [{"unexpected": SECRET}, initialize()],
            ["server/discover", "initialize", "notifications/initialized"],
            LEGACY,
        ),
        (
            "auto",
            [discovery([LEGACY]), initialize()],
            ["server/discover", "initialize", "notifications/initialized"],
            LEGACY,
        ),
        (
            "auto",
            [
                {
                    "code": -32022,
                    "message": SECRET,
                    "data": {"supported": [PROTOCOL_VERSION], "requested": PROTOCOL_VERSION},
                },
                discovery(),
            ],
            ["server/discover", "server/discover"],
            PROTOCOL_VERSION,
        ),
        (
            "auto",
            [
                {"code": -32601, "message": SECRET},
                {
                    "code": -32022,
                    "message": SECRET,
                    "data": {"supported": [PROTOCOL_VERSION], "requested": PROTOCOL_VERSION},
                },
                discovery(),
            ],
            ["server/discover", "initialize", "server/discover"],
            PROTOCOL_VERSION,
        ),
        (
            "auto",
            [httpx2.Response(404), initialize()],
            ["server/discover", "initialize", "notifications/initialized"],
            LEGACY,
        ),
    ],
)
def test_actual_sdk_negotiation_sequence_and_safe_status(host, mode, replies, methods, version, caplog):
    create, observed = host

    async def scenario():
        owner, status = create(mode, replies.copy(), required=["tools"])
        try:
            await owner.prepare()
            async with asyncio.timeout(1):
                while len(observed) < len(methods):
                    await asyncio.sleep(0)
            state = status()
            assert state["configured_protocol"] == mode
            assert state["negotiated_protocol"] == version
            assert "protocol_version" not in state
            assert observed == methods
            assert [item["method"] for item in state["negotiation_attempts"]] == [
                m for m in methods if m in ("initialize", "server/discover")
            ]
            assert state["capabilities"] == ["tools"] and state["accepting"]
            assert SECRET not in repr(state) + caplog.text
        finally:
            await owner.clean()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mode,replies,code,methods",
    [
        ("legacy", [initialize("2025-06-18")], "unsupported_protocol", ["initialize"]),
        ("legacy", [initialize("2099-01-01")], "unsupported_protocol", ["initialize"]),
        ("legacy", [initialize(tools=False)], "missing_capability", ["initialize", "notifications/initialized"]),
        (PROTOCOL_VERSION, [discovery([LEGACY])], "unsupported_protocol", ["server/discover"]),
        (PROTOCOL_VERSION, [{"code": -32603, "message": SECRET}], "protocol_error", ["server/discover"]),
        (
            "auto",
            [{"code": -32022, "message": SECRET, "data": {"supported": ["2099-01-01"], "requested": PROTOCOL_VERSION}}],
            "unsupported_protocol",
            ["server/discover"],
        ),
        (
            "auto",
            [{"code": -32603, "message": SECRET}, {"code": -32601, "message": SECRET}],
            "protocol_error",
            ["server/discover", "initialize"],
        ),
        ("auto", [httpx2.Response(401, text=SECRET)], "authentication_failed", ["server/discover"]),
        ("auto", [httpx2.Response(403, text=SECRET)], "authentication_failed", ["server/discover"]),
        ("legacy", [httpx2.Response(403, text=SECRET)], "authentication_failed", ["initialize"]),
        ("auto", [httpx2.Response(503, text=SECRET)], "http_failed", ["server/discover"]),
        (
            "auto",
            [httpx2.Response(307, headers={"Location": "http://localhost/other"})],
            "redirect_rejected",
            ["server/discover"],
        ),
        (
            "auto",
            [httpx2.Response(200, content=SECRET, headers={"Content-Type": "application/json"})],
            "invalid_protocol_response",
            ["server/discover"],
        ),
        ("legacy", [{"bad": SECRET}], "invalid_protocol_response", ["initialize"]),
        ("auto", [httpx2.ConnectError("network unavailable")], "transport_failed", ["server/discover"]),
    ],
)
def test_errors_do_not_fabricate_a_version_or_retry_auth(host, mode, replies, code, methods, caplog):
    create, observed = host

    async def scenario():
        owner, status = create(mode, replies.copy(), required=["tools"])
        try:
            with pytest.raises(MCPClientError, match=code):
                await owner.prepare()
            assert observed == methods
            assert status()["negotiated_protocol"] == (LEGACY if code == "missing_capability" else None)
            assert status()["error"] == code and not status()["accepting"]
            assert SECRET not in caplog.text
        finally:
            await owner.clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["legacy", "auto", PROTOCOL_VERSION])
def test_one_startup_budget_and_cancellation_close_transport(host, startup_timeouts, mode):
    create, observed = host

    async def scenario():
        entered, finished = asyncio.Event(), asyncio.Event()

        async def stuck(method):
            entered.set()
            try:
                assert len(startup_timeouts) == 1
                startup_timeouts[0].reschedule(asyncio.get_running_loop().time())
                await asyncio.Event().wait()
            finally:
                finished.set()

        owner, status = create(mode, [stuck], startup=10)
        try:
            with pytest.raises(MCPClientError, match="connect_timeout"):
                await owner.prepare()
            assert entered.is_set() and finished.is_set()
            assert observed == ["initialize" if mode == "legacy" else "server/discover"]
            assert status()["negotiated_protocol"] is None
        finally:
            await owner.clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["legacy", "auto", PROTOCOL_VERSION])
def test_tool_rpc_error_is_not_a_negotiation_trigger(host, mode):
    create, observed = host

    async def scenario():
        owner, status = create(
            mode, [initialize() if mode == "legacy" else discovery(), {"code": -32010, "message": SECRET}]
        )
        try:
            await owner.prepare()
            attempts = status()["negotiation_attempts"]
            async with owner.connection("test") as client:
                with pytest.raises(MCPError):
                    await client.session.call_tool("effect", {}, allow_input_required=True)
            assert observed.count("tools/call") == 1
            assert status()["negotiation_attempts"] == attempts
            assert observed.count("initialize") == (1 if mode == "legacy" else 0)
        finally:
            await owner.clean()

    asyncio.run(scenario())
