"""验证 v2 声明、惰性凭证、运行期配置与连接收尾。"""

import asyncio
import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import install_lifecycle_slots
from aurora_mcp import CLIENT_STATUS, CONFIG_STATE, MCPClientError, MCPClients
from aurora_mcp import transports as module
from aurora_mcp.configuration import MCP_CONFIG, PROTOCOL_VERSION, configured_servers
from aurora_mcp.credentials import resolve_values
from mcp.types import ServerCapabilities


def remote(**kwargs):
    return {"type": "remote", "url": "http://localhost/mcp", "protocol": PROTOCOL_VERSION, **kwargs}


def config(server=None, **kwargs):
    return {"schema_version": 2, "servers": {"Test.Name": remote() if server is None else server}, **kwargs}


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": 2, "servers": {"name\n": remote()}},
        config({"type": "local", "command": ["python"], "environment": {"APP\n": "dev"}}),
        config(remote(tools={"include": ["echo"], "aliases": {"echo": "alias\n"}})),
    ],
)
def test_identifiers_reject_trailing_newline(value):
    with pytest.raises(ValueError):
        MCP_CONFIG.parse(value)


def owner_for(value, resolver=lambda name: pytest.fail("不得解析凭证")):
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, load_plugins(enabled=["aurora_config", "aurora_mcp"]))
    ctx, hooks = Context(registry), HookConnections(registry)
    ctx.set(CONFIG_STATE, value)
    owner = MCPClients(ctx, hooks, resolve_env=resolver)
    owner.configure()
    return owner, ctx


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"schema_version": 1},
        {"schema_version": True},
        {"connections": []},
        {"schema_version": 2, "connections": []},
        {"schema_version": 2, "tools": []},
    ],
)
def test_invalid_version_and_layout_are_rejected(value):
    with pytest.raises(ValueError):
        MCP_CONFIG.parse(value)


@pytest.mark.parametrize(
    "server",
    [
        remote(command=["python"]),
        {"type": "local", "command": ["python"], "url": "http://localhost/mcp"},
        {"type": "local", "command": []},
        {"type": "local", "command": ["python", "{env:TOKEN}"]},
        {"type": "local", "command": ["python"], "environment": {"SECRET": "literal"}},
        remote(oauth=True),
        remote(headers={"Authorization": "Bearer literal"}),
        remote(headers={"X-Test": "ok", "x-test": "different"}),
        remote(headers={"X-Test": "x\r\nInjected: yes"}),
        remote(headers={"MCP-Protocol-Version": "2026-07-28"}),
        remote(timeout={"startup": float("inf")}),
        remote(tools={"include": ["*", "echo"]}),
        remote(tools={"include": [], "aliases": {"echo": "old_echo"}}),
    ],
)
def test_invalid_declarations_fail_without_resources(server):
    with pytest.raises(ValueError):
        MCP_CONFIG.parse(config(server))


def test_defaults_override_and_local_declaration_are_inert(tmp_path):
    value = config(
        {
            "type": "local",
            "command": ["C:\\Program Files\\Python\\python.exe", "", "argument with space"],
            "cwd": "not-created",
            "environment": {"APP_MODE": "dev", "APP_TOKEN": "{env:TOKEN}"},
            "timeout": {"execution": 90},
        },
        timeout={"startup": 12, "execution": 60},
    )
    original = copy.deepcopy(value)
    parsed = cast(dict, MCP_CONFIG.parse(value))
    assert value == original
    server = configured_servers(parsed)["Test.Name"]
    assert server["protocol"] == "legacy"
    assert server["timeout"] == {"startup": 12, "catalog": 30, "execution": 90, "shutdown": 10}
    assert server["tools"] == {"include": ["*"], "exclude": [], "aliases": {}}
    assert server["command"] == original["servers"]["Test.Name"]["command"]
    assert not (tmp_path / "not-created").exists()


def test_local_service_requires_explicit_workspace_before_starting():
    async def scenario():
        owner, ctx = owner_for(config({"type": "local", "command": ["unavailable"]}))
        try:
            with pytest.raises(MCPClientError, match="workspace_required"):
                await owner.prepare()
        finally:
            await owner.clean()
            ctx.close()

    asyncio.run(scenario())


def test_disabled_servers_do_not_resolve_connect_or_publish(monkeypatch):
    monkeypatch.setattr(module, "open_client", lambda *a: pytest.fail("禁用项不得创建资源"))

    async def scenario():
        owner, ctx = owner_for(config(remote(enabled=False, headers={"Authorization": "{env:MISSING}"})))
        try:
            assert [record.address.key for record in ctx.snapshot().records] == [CONFIG_STATE]
            await owner.prepare()
            with pytest.raises(MCPClientError, match="connection_unavailable"):
                async with owner.connection("Test.Name"):
                    pass
            assert [record.address.key for record in ctx.snapshot().records] == [CONFIG_STATE]
        finally:
            await owner.clean()
            ctx.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("secret", [None, "", " ", "bad\r\nheader", "bad\0value", "非ASCII"])
def test_runtime_header_failure_does_not_expose_values(monkeypatch, secret):
    monkeypatch.setattr(module.httpx2, "AsyncClient", lambda **kw: pytest.fail("错误凭证不得创建网络资源"))

    async def scenario():
        owner, ctx = owner_for(config(remote(headers={"Authorization": "Bearer {env:TOKEN}"})), lambda name: secret)
        try:
            with pytest.raises(MCPClientError, match="credential_unavailable") as error:
                await owner.prepare()
            assert error.value.location == "servers.Test.Name.headers.Authorization"
            status = cast(
                dict, ctx.get(CLIENT_STATUS, location={"owner": owner.instance_id, "connection_id": "Test.Name"})
            )
            assert status["error_location"] == error.value.location
            assert ctx.snapshot(persistent_only=True).records == ()
        finally:
            await owner.clean()
            ctx.close()

    asyncio.run(scenario())


def test_environment_references_support_prefixes_without_expanding_twice():
    env = {"ONE": "{env:OTHER}", "TWO": "中文"}
    assert resolve_values({"APP": "{env:ONE}/{env:TWO}"}, env.get, headers=False) == {"APP": "{env:OTHER}/中文"}


def test_shutdown_budget_preserves_cleanup_for_later_wait(monkeypatch):
    async def scenario():
        closing, release = asyncio.Event(), asyncio.Event()
        finished = []

        @asynccontextmanager
        async def connect(*args, **kwargs):
            try:
                yield SimpleNamespace(server_capabilities=ServerCapabilities(), protocol_version=PROTOCOL_VERSION)
            finally:
                closing.set()
                await release.wait()
                finished.append(True)

        monkeypatch.setattr(module, "open_client", connect)
        owner, ctx = owner_for(config(remote(timeout={"shutdown": 0.02})))
        await owner.prepare()
        with pytest.raises(TimeoutError):
            await owner.clean()
        assert closing.is_set() and not finished
        release.set()
        await owner.clean()
        assert finished == [True]
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("aurora-mcp:")]
        ctx.close()

    asyncio.run(scenario())
