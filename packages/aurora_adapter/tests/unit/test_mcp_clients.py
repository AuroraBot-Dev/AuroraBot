"""验证 MCP 声明、连接所有权、取消和失败边界；不访问外部服务。"""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import httpx2
import pytest
from aurora_adapter.mcp import CLIENT_STATUS, CONFIG_STATE, PROTOCOL_VERSION, MCPClientError, MCPClients
from aurora_adapter.mcp import transports as module
from aurora_adapter.mcp.configuration import MCP_CONFIG
from aurora_adapter.mcp.negotiation import validate_discovery
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import install_lifecycle_slots
from mcp.types import DiscoverResult, ServerCapabilities, ToolsCapability


def declaration(identity="local", **kwargs):
    return {identity: {"type": "remote", "protocol": PROTOCOL_VERSION, "url": "http://127.0.0.1:8000/mcp", **kwargs}}


def configuration(values):
    return {"schema_version": 2, "servers": {key: value for item in values for key, value in item.items()}}


def environment(values=None):
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, load_plugins(enabled=["aurora_config", "aurora_adapter.mcp"]))
    ctx, hooks = Context(registry), HookConnections(registry)
    owner = MCPClients(ctx, hooks)
    ctx.set(CONFIG_STATE, configuration([declaration()] if values is None else values))
    owner.configure()
    return owner, ctx


def state(ctx, identity="local"):
    return cast(dict, ctx.get(CLIENT_STATUS, location={"owner": "aurora_adapter/mcp", "connection_id": identity}))


def fake_client():
    return SimpleNamespace(
        server_capabilities=ServerCapabilities(tools=ToolsCapability()), protocol_version=PROTOCOL_VERSION
    )


@pytest.mark.parametrize(
    "value",
    [
        {"unknown": True},
        {"connections": []},
        configuration([declaration("")]),
        configuration([declaration("a\nb")]),
        configuration([declaration(required_capabilities=["imaginary"])]),
        configuration([declaration(required_capabilities=["tools", "tools"])]),
        configuration([declaration(timeout={"startup": 0})]),
        configuration([declaration(timeout={"execution": True})]),
        configuration([declaration(token="secret")]),
        configuration([declaration(headers={"Authorization": "{env:not valid}"})]),
        *(
            configuration([declaration(url=url)])
            for url in [
                "file:///tmp/server",
                "http://a:secret@localhost/mcp",
                "http://localhost/mcp?token=secret",
                "http://localhost/mcp#secret",
                "http://localhost:bad/mcp",
                "http://localhost:0/mcp",
                "http://local host/mcp",
            ]
        ),
    ],
)
def test_invalid_configuration_is_rejected_before_connecting(value):
    with pytest.raises(ValueError):
        MCP_CONFIG.parse(value)


def test_defaults_and_discovery_are_inert(monkeypatch):
    assert MCP_CONFIG.parse({"schema_version": 2}) == {"schema_version": 2, "servers": {}, "timeout": {}}
    value = configuration([declaration()])
    parsed = cast(dict, MCP_CONFIG.parse(value))
    assert parsed["servers"]["local"]["enabled"] is True
    assert "enabled" not in value["servers"]["local"]
    monkeypatch.setattr(module, "Client", lambda *a, **kw: pytest.fail("发现阶段不得创建客户端"))
    with pytest.raises(ValueError):
        load_plugins(enabled=["aurora_adapter.mcp"])
    _owner, ctx = environment()
    assert state(ctx)["phase"] == "configured"
    assert ctx.snapshot(persistent_only=True).records == ()
    ctx.close()


def test_capabilities_and_protocol_are_checked_without_assuming_unknown_features():
    result = DiscoverResult(
        supported_versions=[PROTOCOL_VERSION], capabilities=ServerCapabilities(tools=ToolsCapability())
    )
    validate_discovery(result, ["tools"])
    with pytest.raises(MCPClientError, match="missing_capability"):
        validate_discovery(result, ["resources"])
    result.supported_versions = ["2025-11-25"]
    with pytest.raises(MCPClientError, match="unsupported_protocol"):
        validate_discovery(result, [])


@pytest.mark.parametrize("failure", ["failure", "timeout", "cancel"])
def test_partial_prepare_failure_closes_existing_clients(monkeypatch, failure):
    async def scenario():
        events = []
        started = asyncio.Event()

        @asynccontextmanager
        async def connect(config, resolver, negotiation, *, workspace_root=None):
            identity = config["connection_id"]
            task = asyncio.current_task()
            events.append((identity, "enter"))
            try:
                if identity == "bad":
                    started.set()
                    if failure == "failure":
                        raise RuntimeError("secret-token")
                    await asyncio.Event().wait()
                yield fake_client()
            finally:
                assert task is asyncio.current_task()
                events.append((identity, "exit"))

        monkeypatch.setattr(module, "open_client", connect)
        owner, ctx = environment([declaration("good"), declaration("bad", timeout={"startup": 0.02})])
        prepare = asyncio.create_task(owner.prepare())
        await started.wait()
        if failure == "cancel":
            prepare.cancel()
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else MCPClientError) as error:
            await prepare
        assert "secret-token" not in str(error.value)
        await owner.clean()
        assert events.count(("good", "exit")) == events.count(("bad", "exit")) == 1
        assert state(ctx, "good")["phase"] == "closed"
        assert (
            state(ctx, "bad")["error"]
            == {"failure": "connect_failed", "timeout": "connect_timeout", "cancel": "connect_cancelled"}[failure]
        )
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("aurora-mcp:")]
        ctx.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("wait_cancel", [False, True])
def test_close_wait_can_resume_without_recancelling_cleanup(monkeypatch, wait_cancel):
    async def scenario():
        closing, release = asyncio.Event(), asyncio.Event()
        exits = []

        @asynccontextmanager
        async def connect(config, resolver, negotiation, *, workspace_root=None):
            task = asyncio.current_task()
            try:
                yield fake_client()
            finally:
                closing.set()
                await release.wait()
                assert task is asyncio.current_task()
                exits.append("closed")

        monkeypatch.setattr(module, "open_client", connect)
        owner, ctx = environment()
        await owner.prepare()
        close = asyncio.create_task(owner.clean())
        await closing.wait()
        if wait_cancel:
            close.cancel()
            with pytest.raises(asyncio.CancelledError):
                await close
        else:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(close, 0.02)
        assert state(ctx)["phase"] == "closing"
        with pytest.raises(MCPClientError, match="not_accepting"):
            async with owner.connection("local"):
                pass
        release.set()
        await owner.clean()
        await owner.clean()
        assert exits == ["closed"]
        assert state(ctx)["phase"] == "closed"
        ctx.close()

    asyncio.run(scenario())


def test_shutdown_drains_borrowers_before_closing_client(monkeypatch):
    async def scenario():
        entered, unwinding, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        events = []

        @asynccontextmanager
        async def connect(config, resolver, negotiation, *, workspace_root=None):
            try:
                yield fake_client()
            finally:
                events.append("client.closed")

        monkeypatch.setattr(module, "open_client", connect)
        owner, ctx = environment()
        await owner.prepare()

        async def borrower():
            async with owner.connection("local"), owner.connection("local"):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    unwinding.set()
                    await release.wait()
                    events.append("borrower.finished")

        task = asyncio.create_task(borrower())
        await entered.wait()
        close = asyncio.create_task(owner.clean())
        await unwinding.wait()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(close, 0.02)
        assert not events
        retry = asyncio.create_task(owner.clean())
        await asyncio.sleep(0)
        release.set()
        await retry
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events == ["borrower.finished", "client.closed"]
        ctx.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("error_type", [RuntimeError, TimeoutError, asyncio.CancelledError, httpx2.ConnectError])
def test_close_failure_is_explicit_and_never_reported_as_closed(monkeypatch, error_type):
    async def scenario():
        @asynccontextmanager
        async def connect(config, resolver, negotiation, *, workspace_root=None):
            yield fake_client()
            raise error_type("secret-close-error")

        monkeypatch.setattr(module, "open_client", connect)
        owner, ctx = environment()
        await owner.prepare()
        for _ in range(2):
            with pytest.raises(MCPClientError, match="close_failed"):
                await owner.clean()
        assert state(ctx)["phase"] == "failed"
        assert "secret" not in str(state(ctx))
        ctx.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["ok", "missing", "unknown_advertised", "old_protocol", "rejected", "missing_token"])
def test_real_sdk_discovery_credentials_and_capability_failures(monkeypatch, caplog, mode):
    async def scenario():
        secret = "test-only-runtime-token"
        requests, resolved, clients = [], [], []
        original = httpx2.AsyncClient

        async def respond(request):
            await asyncio.sleep(0.01)
            data = json.loads(request.content)
            requests.append(data)
            assert request.headers["Authorization"] == f"Bearer {secret}"
            assert request.headers["MCP-Protocol-Version"] == PROTOCOL_VERSION
            assert data["method"] == "server/discover"
            if mode == "rejected":
                return httpx2.Response(
                    200, json={"jsonrpc": "2.0", "id": data["id"], "error": {"code": -32601, "message": secret}}
                )
            result = DiscoverResult(
                supported_versions=["2025-11-25" if mode == "old_protocol" else PROTOCOL_VERSION],
                capabilities=ServerCapabilities() if mode == "missing" else ServerCapabilities(tools=ToolsCapability()),
            ).model_dump(by_alias=True, exclude_none=True)
            if mode == "unknown_advertised":
                result["capabilities"]["imaginary"] = {"untrusted": secret}
            return httpx2.Response(200, json={"jsonrpc": "2.0", "id": data["id"], "result": result})

        def http_client(**kwargs):
            client = original(**kwargs, transport=httpx2.MockTransport(respond))
            clients.append(client)
            return client

        def resolver(name):
            resolved.append(name)
            return None if mode == "missing_token" else secret

        monkeypatch.setattr(module.httpx2, "AsyncClient", http_client)
        owner, ctx = environment(
            [
                declaration(
                    required_capabilities=["tools"],
                    headers={"Authorization": "Bearer {env:TEST_MCP_TOKEN}"},
                    timeout={"execution": 0.001},
                )
            ]
        )
        owner._resolve_env = resolver
        assert resolved == []
        try:
            if mode in ("ok", "unknown_advertised"):
                await owner.prepare()
                assert state(ctx)["capabilities"] == ["tools"]
            else:
                expected = {
                    "missing": "missing_capability",
                    "old_protocol": "unsupported_protocol",
                    "rejected": "protocol_error",
                    "missing_token": "credential_unavailable",
                }[mode]
                with pytest.raises(MCPClientError, match=expected) as error:
                    await owner.prepare()
                assert secret not in str(error.value)
            assert resolved == ["TEST_MCP_TOKEN"]
            assert len(requests) == (0 if mode == "missing_token" else 1)
            assert secret not in str(ctx.snapshot()) + caplog.text
            assert ctx.snapshot(persistent_only=True).records == ()
        finally:
            await owner.clean()
            assert all(client.is_closed for client in clients)
            ctx.close()

    asyncio.run(scenario())
