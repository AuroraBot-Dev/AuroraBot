"""验证 v2 声明、惰性凭证、无损迁移及不覆盖用户文件。"""

import asyncio
import copy
import os
import subprocess
import sys
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import tomli_w
from aurora_adapter.mcp import CLIENT_STATUS, CONFIG_STATE, MCPClientError, MCPClients
from aurora_adapter.mcp import transports as module
from aurora_adapter.mcp.configuration import MCP_CONFIG, PROTOCOL_VERSION, configured_servers
from aurora_adapter.mcp.credentials import resolve_values
from aurora_adapter.mcp.migrate import migrate
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import install_lifecycle_slots
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
    register_plugins(registry, load_plugins(enabled=["aurora_config", "aurora_adapter.mcp"]))
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
def test_version_and_legacy_layout_require_explicit_migration(value):
    with pytest.raises(ValueError) as error:
        MCP_CONFIG.parse(value)
    if "connections" in value or "tools" in value:
        assert "aurora_adapter.mcp.migrate" in str(error.value)


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


def legacy():
    return {
        "connections": [
            {
                "connection_id": "Test.Name",
                "url": "http://localhost/mcp",
                "token_env": "MCP_TOKEN",
                "connect_timeout": 7,
                "request_timeout": 19,
            },
            {"connection_id": "world", "url": "http://localhost/world"},
        ],
        "tools": [{"connection_id": "Test.Name", "remote_name": "remote.echo", "name": "old_echo"}],
    }


def test_migration_preserves_identity_exposure_timeouts_and_references(monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "must-never-be-read")
    source = legacy()
    original = copy.deepcopy(source)
    migrated = migrate(source)
    assert source == original
    assert tomllib.loads(tomli_w.dumps(migrated)) == migrated
    servers = configured_servers(cast(dict, MCP_CONFIG.parse(migrated)))
    assert list(servers) == ["Test.Name", "world"]
    assert servers["world"]["tools"]["include"] == []
    assert servers["Test.Name"]["tools"] == {
        "include": ["remote.echo"],
        "exclude": [],
        "aliases": {"remote.echo": "old_echo"},
    }
    assert servers["Test.Name"]["headers"] == {"Authorization": "Bearer {env:MCP_TOKEN}"}
    assert servers["Test.Name"]["protocol"] == PROTOCOL_VERSION
    assert servers["Test.Name"]["timeout"] == {"startup": 7, "catalog": 19, "execution": 19, "shutdown": 10}
    assert "must-never-be-read" not in repr(migrated)
    assert migrate({}) == {"schema_version": 2, "servers": {}}


@pytest.mark.parametrize(
    "problem", ["multiple_aliases", "missing_connection", "duplicate_connection", "mixed", "invalid_timeout"]
)
def test_lossy_or_invalid_migration_is_rejected(problem):
    value = legacy()
    if problem == "multiple_aliases":
        value["tools"].append({**value["tools"][0], "name": "another"})
    elif problem == "missing_connection":
        value["tools"][0]["connection_id"] = "missing"
    elif problem == "duplicate_connection":
        value["connections"].append(value["connections"][0])
    elif problem == "mixed":
        value["servers"] = {}
    else:
        value["connections"][0]["request_timeout"] = -1
    with pytest.raises(ValueError):
        migrate(value)


def run_migration(source: Path, output: Path):
    return subprocess.run(
        [sys.executable, "-m", "aurora_adapter.mcp.migrate", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=15,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "MCP_TOKEN": "runtime-secret"},
    )


def test_migration_command_writes_only_new_candidate_and_safe_diff(tmp_path):
    source, output = tmp_path / "config.toml", tmp_path / "candidate.toml"
    original = "# comment-secret\n" + tomli_w.dumps(legacy())
    source.write_text(original, encoding="utf-8")
    result = run_migration(source, output)
    assert result.returncode == 0, result.stderr
    assert source.read_text(encoding="utf-8") == original
    assert tomllib.loads(output.read_text(encoding="utf-8")) == migrate(legacy())
    assert "old_echo" in result.stdout and "tool_timeout" in result.stdout
    assert not any(secret in result.stdout + result.stderr for secret in ("runtime-secret", "comment-secret"))
    before = output.read_bytes()
    assert run_migration(source, output).returncode == 1
    assert output.read_bytes() == before
    assert run_migration(source, source).returncode == 1
    assert source.read_text(encoding="utf-8") == original
