"""验证 MCP 独立宿主与真实本机 Streamable HTTP 的进程级联通。"""

import asyncio
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest
from aurora_adapter.mcp import PROTOCOL_VERSION, MCPClients
from aurora_adapter.mcp import transports as module
from aurora_config import configuration_component
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.storage import StorageService
from mcp.types import ServerCapabilities


def test_mcp_roundtrip_without_execution_world_or_product_packages(tmp_path):
    launcher = """
import importlib.abc
import runpy
import sys
blocked = {'aurora_agent', 'aurora_bot', 'aurora_control', 'aurora_adapter.model',
           'aurora_cli', 'aurora_api', 'aurora_world'}
class AbsentPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + '.') for item in blocked):
            raise ModuleNotFoundError('MCP 独立环境不提供：' + fullname)
sys.meta_path.insert(0, AbsentPackages())
source = sys.argv.pop(1)
runpy.run_path(source, run_name='__main__')
assert not any(name == item or name.startswith(item + '.') for name in sys.modules for item in blocked)
"""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_roundtrip.py"
    result = subprocess.run(
        [sys.executable, "-c", launcher, str(fixture), str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "protocol": "2026-07-28",
        "roundtrip": True,
        "disconnect_reported": True,
        "snapshot_empty": True,
    }


def test_mcp_distribution_and_plugin_boundaries():
    requirements = metadata.requires("aurora-adapter")
    assert requirements is not None
    assert all("extra == 'mcp-bot'" in item for item in requirements if item.startswith("aurora-bot"))
    assert all(
        "extra == 'mcp-tools'" in item or "extra == 'mcp-bot'" in item
        for item in requirements
        if item.startswith("aurora-agent")
    )
    assert all(
        "extra == 'mcp-world'" in item or "extra == 'mcp-bot'" in item
        for item in requirements
        if item.startswith("aurora-world")
    )
    assert "mcp==2.3.0; extra == 'mcp'" in requirements
    plugins = load_plugins(enabled=["aurora_config", "aurora_adapter.mcp"])
    plugin = next(item for item in plugins if item.name == "aurora_adapter.mcp")
    assert all(entry.id.namespace == "org.aurora.adapter" for entry in plugin.entries)


@pytest.mark.parametrize("selection", ["empty", "selected", "failure", "cancel"])
def test_configured_host_preserves_files_and_finishes_resources_before_snapshot(tmp_path, monkeypatch, selection):
    async def scenario():
        events = []
        entered = asyncio.Event()

        @asynccontextmanager
        async def connect(config, resolver, negotiation, *, workspace_root=None):
            events.append("created")
            try:
                entered.set()
                if selection == "failure":
                    raise RuntimeError("sensitive-server-error")
                if selection == "cancel":
                    await asyncio.Event().wait()
                yield SimpleNamespace(server_capabilities=ServerCapabilities(), protocol_version=PROTOCOL_VERSION)
            finally:
                events.append("closed")

        monkeypatch.setattr(module, "open_client", connect)
        registry = bootstrap()
        install_lifecycle_slots(registry)
        register_plugins(registry, load_plugins(enabled=["aurora_config", "aurora_adapter.mcp"]))
        ctx, hooks, storage = Context(registry), HookConnections(registry), StorageService(tmp_path)
        path = storage.configuration_directory() / "org.aurora.adapter" / "mcp.toml"
        text = '# 用户配置\nschema_version = 2\n[servers.test]\ntype = "remote"\nprotocol = "2026-07-28"\nurl = "http://127.0.0.1:8000/mcp"\n'
        if selection != "empty":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        owner = MCPClients(ctx, hooks)
        store = storage.snapshot_store()
        save = store.save

        def save_after_close(snapshot):
            assert events in ([], ["created", "closed"])
            events.append("saved")
            save(snapshot)

        monkeypatch.setattr(store, "save", save_after_close)
        host = Lifecycle(
            ctx,
            hooks,
            [owner.component(), configuration_component(registry, ctx, hooks, storage)],
            persistence=ContextPersistence(ctx, store, interval=60),
            storage=storage,
        )
        start = asyncio.create_task(host.start())
        if selection == "cancel":
            await entered.wait()
            start.cancel()
            with pytest.raises(asyncio.CancelledError):
                await start
        elif selection == "failure":
            with pytest.raises(module.MCPClientError, match="connect_failed"):
                await start
        else:
            await start
        original = path.read_text(encoding="utf-8")
        if selection != "empty":
            assert original == text
        else:
            assert "schema_version = 2" in original and "[servers]" in original
        await host.stop()
        assert path.read_text(encoding="utf-8") == original
        assert store.load() == ()
        assert events == (["saved"] if selection == "empty" else ["created", "closed", "saved"])
        assert host.state == "stopped"

    asyncio.run(scenario())
