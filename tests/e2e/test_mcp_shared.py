"""真实 HTTP/stdio 与产品装配共用工具、世界来源，验证关闭顺序和恢复边界。"""

import asyncio
import json
import socket
import subprocess
import sys
import tomllib
from contextlib import asynccontextmanager
from functools import wraps
from io import StringIO
from pathlib import Path
from typing import cast

import pytest
import tomli_w
from aurora_adapter.mcp import CLIENT_STATUS, MCPClients
from aurora_adapter.mcp.bot import assemble
from aurora_adapter.mcp.catalog import automatic_name
from aurora_adapter.mcp.errors import MCPClientError
from aurora_adapter.mcp.preset import initialize
from aurora_adapter.mcp.tool_execution import MCPTool
from aurora_adapter.mcp.world import WORLD_SOURCE, WORLD_STATUS, MCPWorldError, _ResourceSource
from aurora_adapter.model.config import ADAPTERS, ModelAdapter
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_bot.operations import RUN_CONTROL, RunOperations
from aurora_config import configuration_component
from aurora_core import Id
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import STOP, Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from aurora_world import ENVIRONMENT, RECORDS, SOURCE_STATUS
from aurora_world.environment import TIME
from test_mcp_stdio import alive

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/mcp_shared_server.py"
ADAPTER = Id("dev.shared:adapters/fake")


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.01)


@asynccontextmanager
async def services(root, transport):
    declarations, processes = {}, []
    try:
        for index, kind in enumerate(["local", "remote"] if transport == "mixed" else [transport]):
            name = f"server{index}"
            directory = root / name
            directory.mkdir()
            command = [sys.executable, str(FIXTURE), str(directory)]
            if kind == "remote":
                with socket.socket() as available:
                    available.bind(("127.0.0.1", 0))
                    port = available.getsockname()[1]
                process = await asyncio.create_subprocess_exec(
                    *command,
                    "--port",
                    str(port),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                processes.append(process)
                async with asyncio.timeout(10):
                    while True:
                        assert process.returncode is None
                        try:
                            _, writer = await asyncio.open_connection("127.0.0.1", port)
                            writer.close()
                            await writer.wait_closed()
                            break
                        except OSError:
                            await asyncio.sleep(0.01)
                declaration = {"type": kind, "url": f"http://127.0.0.1:{port}/mcp"}
            else:
                declaration = {"type": kind, "command": command}
            declarations[name] = {**declaration, "protocol": "auto"}
        yield declarations, processes
    finally:
        for name in declarations:
            (root / name / "release").touch()
        for process in processes:
            if process.returncode is None:
                process.terminate()
            await process.wait()


def setup(root, declarations, mode, monkeypatch, events):
    assert initialize(root, world=True, output=StringIO()) == 0
    host_path = root / "config/host.toml"
    host_config = tomllib.loads(host_path.read_text(encoding="utf-8"))
    host_config["plugins"].append("aurora_world.environment")
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, load_plugins(enabled=host_config["plugins"]))
    models = []
    name = automatic_name("server0", "probe")

    async def factory(config, *, api_key=None):
        if mode == "model_failure":
            raise RuntimeError("测试模型工厂失败")

        def reply(request):
            if any(message["role"] == "tool" for message in request["messages"]):
                return FakeReply(("完成",))
            return FakeReply(tool_calls=({"id": "call", "name": name, "arguments": {}},))

        model = FakeModel(reply)
        models.append(model)
        return model

    registry.register(RegistryEntry(ADAPTER, "adapter", ModelAdapter("chat", factory), "test", register_to=ADAPTERS))
    declarations = {
        name: {**value, "timeout": {"execution": 0.5 if mode == "timeout" else 30}}
        for name, value in declarations.items()
    }
    if mode == "catalog_failure":
        declarations["server0"]["tools"] = {"include": ["missing"]}
    if mode == "source_failure":
        declarations["server0"]["protocol"] = "legacy"
    values = {
        "org.aurora.adapter/mcp.toml": {"schema_version": 2, "servers": declarations},
        "org.aurora.adapter/model/profiles.toml": {"test": {"adapter": str(ADAPTER), "model": "fake"}},
        "org.aurora.adapter/model/bindings.toml": {"reasoning": "test"},
        "org.aurora.bot/config.toml": {"instance_id": "main", "model_role": "reasoning", "streaming": False},
        "org.aurora.world/config.toml": {
            "sources": [
                {"source": str(TIME), "source_id": "clock", "config": {}},
                *[
                    {
                        "source": str(WORLD_SOURCE),
                        "source_id": name,
                        "config": {
                            "connection_id": name,
                            "resources": [{"uri": "test://event", "mode": "event"}],
                        },
                    }
                    for name in declarations
                ],
            ]
        },
    }
    for relative, value in values.items():
        (root / "config" / relative).write_text(tomli_w.dumps(value), encoding="utf-8")
    ctx, hooks, storage = Context(registry), HookConnections(registry), StorageService(root)
    components = assemble(registry=registry, ctx=ctx, hooks=hooks, storage=storage, workspace_root=root)
    store = storage.snapshot_store()
    original_save = store.save

    def save(snapshot):
        assert "clients.closed" in events
        if mode not in ("catalog_failure", "model_failure"):
            assert "tool.closed" in events and models
        assert all(model.closed for model in models)
        events.append("snapshot")
        original_save(snapshot)

    monkeypatch.setattr(store, "save", save)
    host = Lifecycle(
        ctx,
        hooks,
        [configuration_component(registry, ctx, hooks, storage), *components],
        persistence=ContextPersistence(ctx, store, interval=60),
        storage=storage,
    )
    return host, ctx, hooks, cast(RunOperations, registry.get(RUN_CONTROL).target), models, store


@pytest.mark.parametrize(
    "transport,mode",
    [
        ("remote", "source_stop"),
        ("remote", "timeout"),
        ("local", "cancel"),
        ("local", "host_stop"),
        ("mixed", "disconnect"),
        ("remote", "close_cancel"),
        ("local", "close_timeout"),
    ],
)
def test_shared_product_closes_consumers_before_clients_and_snapshot(tmp_path, monkeypatch, transport, mode):
    async def scenario():
        events = []
        closing, release_close = asyncio.Event(), asyncio.Event()
        clean, close_tool, close_source = MCPClients.clean, MCPTool.close, _ResourceSource.close

        @wraps(clean)
        async def observed_clean(self):
            await clean(self)
            assert "tool.closed" in events
            events.append("clients.closed")

        async def observed_tool_close(self):
            assert "source.closed" in events
            await close_tool(self)
            if mode in ("close_cancel", "close_timeout"):
                closing.set()
                await release_close.wait()
            events.append("tool.closed")

        async def observed_source_close(self):
            await close_source(self)
            events.append("source.closed")

        monkeypatch.setattr(MCPClients, "clean", observed_clean)
        monkeypatch.setattr(MCPTool, "close", observed_tool_close)
        monkeypatch.setattr(_ResourceSource, "close", observed_source_close)
        async with services(tmp_path, transport) as (declarations, processes):
            host, ctx, hooks, operations, models, store = setup(tmp_path, declarations, mode, monkeypatch, events)
            before = {path: path.read_bytes() for path in (tmp_path / "config").rglob("*.toml")}
            await host.start()
            try:
                assert {dict(address.location)["source_id"] for address in ctx.list(key=ENVIRONMENT)} == {"clock"}
                assert len(ctx.list(key=WORLD_STATUS)) == len(declarations)
                assert len(ctx.list(key=SOURCE_STATUS)) == len(declarations) + 1
                handle = operations.submit("调用工具", instance_id="main").run
                directory = tmp_path / "server0"
                await until(lambda: (directory / "entered").exists())
                await until(
                    lambda: (
                        ctx.list(key=RECORDS)
                        and any(record["source_id"] == "server0" for record in cast(dict, ctx.get(RECORDS))["records"])
                    )
                )
                if mode == "source_stop":
                    for connection in hooks.for_slot(STOP, "default/world"):
                        await hooks.invoke(connection)
                    assert cast(
                        dict,
                        ctx.get(CLIENT_STATUS, location={"owner": "aurora_adapter/mcp", "connection_id": "server0"}),
                    )["accepting"]
                    assert not (directory / "finished").exists()
                    (directory / "release").touch()
                elif mode == "cancel":
                    assert await operations.cancel(handle.run_id, instance_id="main")
                elif mode == "host_stop":
                    await host.stop()
                elif mode in ("close_cancel", "close_timeout"):
                    waiter = asyncio.create_task(host.stop())
                    await asyncio.wait_for(closing.wait(), 10)
                    assert "clients.closed" not in events and "snapshot" not in events
                    with pytest.raises((LookupError, RuntimeError)):
                        operations.submit("停止后拒绝", instance_id="main")
                    if mode == "close_cancel":
                        waiter.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await waiter
                    else:
                        with pytest.raises(TimeoutError):
                            await asyncio.wait_for(waiter, 0.01)
                    assert "clients.closed" not in events and "snapshot" not in events
                    release_close.set()
                    await host.stop()
                elif mode == "disconnect":
                    (directory / "disconnect").touch()
                result = await asyncio.wait_for(handle.wait(), 10)
                assert result.status == (
                    "cancelled" if mode in ("cancel", "host_stop", "close_cancel", "close_timeout") else "completed"
                )
                if mode in ("timeout", "disconnect"):
                    observed = next(
                        message for message in models[0].requests[-1]["messages"] if message["role"] == "tool"
                    )
                    failure = json.loads(observed["content"])
                    assert failure["error"]["code"] == ("mcp_timeout" if mode == "timeout" else "mcp_result_unknown")
                if mode == "disconnect":
                    await until(
                        lambda: bool(cast(dict, ctx.get(WORLD_STATUS, location={"source_id": "server0"}))["error"])
                    )
                    if transport == "mixed":
                        assert (
                            cast(dict, ctx.get(WORLD_STATUS, location={"source_id": "server1"}))["phase"] == "listening"
                        )
                        assert cast(
                            dict,
                            ctx.get(
                                CLIENT_STATUS, location={"owner": "aurora_adapter/mcp", "connection_id": "server1"}
                            ),
                        )["accepting"]
                if mode != "disconnect":
                    assert all(process.returncode is None for process in processes)
            finally:
                release_close.set()
                await host.stop()
            assert events[-1] == "snapshot"
            if mode != "disconnect" or transport == "mixed":
                assert all(process.returncode is None for process in processes)
            assert operations.instances == () and all(model.closed for model in models)
            assert all(record.address.key.namespace != "org.aurora.adapter" for record in store.load())
            assert any(record.address.key == RECORDS for record in store.load())
            assert all(path.read_bytes() == content for path, content in before.items())
            assert (tmp_path / "server0/calls").read_text(encoding="utf-8").splitlines() == ["probe"]
            for name, declaration in declarations.items():
                if declaration["type"] == "local":
                    assert not alive(int((tmp_path / name / "pid").read_text()))
            assert not [
                task
                for task in asyncio.all_tasks()
                if task.get_name().startswith(("aurora-mcp:", "mcp-world:", "world-source:"))
            ]
            if mode in ("source_stop", "cancel", "host_stop"):
                events.clear()
                (tmp_path / "server0/release").touch()
                restored_host, restored, _, _, restored_models, _ = setup(
                    tmp_path, declarations, mode, monkeypatch, events
                )
                await restored_host.start()
                try:
                    assert any(
                        record["source_id"] == "server0" for record in cast(dict, restored.get(RECORDS))["records"]
                    )
                    await asyncio.sleep(0.05)
                    assert restored_models[0].requests == []
                    assert (tmp_path / "server0/calls").read_text(encoding="utf-8").splitlines() == ["probe"]
                finally:
                    await restored_host.stop()
                assert events[-1] == "snapshot"
                for name, declaration in declarations.items():
                    if declaration["type"] == "local":
                        assert not alive(int((tmp_path / name / "pid").read_text()))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "transport,mode",
    [("remote", "catalog_failure"), ("local", "model_failure"), ("mixed", "source_failure")],
)
def test_partial_product_startup_closes_prepared_shared_resources(tmp_path, monkeypatch, transport, mode):
    async def scenario():
        events = []
        clean, close_tool = MCPClients.clean, MCPTool.close

        @wraps(clean)
        async def observed_clean(self):
            await clean(self)
            events.append("clients.closed")

        async def observed_tool_close(self):
            await close_tool(self)
            events.append("tool.closed")

        monkeypatch.setattr(MCPClients, "clean", observed_clean)
        monkeypatch.setattr(MCPTool, "close", observed_tool_close)
        async with services(tmp_path, transport) as (declarations, processes):
            host, _, _, operations, models, _ = setup(tmp_path, declarations, mode, monkeypatch, events)
            expected = {
                "catalog_failure": (MCPClientError, "selected_tool_missing"),
                "model_failure": (RuntimeError, "测试模型工厂失败"),
                "source_failure": (MCPWorldError, "unsupported_subscription_protocol"),
            }[mode]
            with pytest.raises(expected[0], match=expected[1]):
                await host.start()
            assert host.state == "stopped" and events[-1] == "snapshot"
            assert operations.instances == () and all(model.closed and not model.requests for model in models)
            for name, declaration in declarations.items():
                assert not (tmp_path / name / "calls").exists()
                if declaration["type"] == "local":
                    assert not alive(int((tmp_path / name / "pid").read_text()))
            assert all(process.returncode is None for process in processes)
            assert not [
                task
                for task in asyncio.all_tasks()
                if task.get_name().startswith(("aurora-mcp:", "mcp-world:", "world-source:"))
            ]

    asyncio.run(scenario())
