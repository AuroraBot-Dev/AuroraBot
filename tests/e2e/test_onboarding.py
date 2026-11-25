"""首次安装助手的补缺初始化、最小装配及真实 stdio 工具往返。"""

import asyncio
import json
import runpy
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import tomli_w
from aurora_adapter.model.config import ADAPTERS, ModelAdapter
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_cli.commander import run_cli
from aurora_config import read_toml
from aurora_config.files import configuration_files
from aurora_core import Id
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import Plugin, load_plugins, register_plugins
from aurora_core.lifecycle import install_lifecycle_slots
from aurora_core.registry import RegistryEntry

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "examples/onboarding/main.py"


def test_initialization_preserves_files_and_validates_minimal_configuration(tmp_path, monkeypatch):
    source = runpy.run_path(str(APPLICATION))

    async def forbidden(*args, **kwargs):
        pytest.fail("初始化不能创建模型、工具连接或运行期宿主")

    monkeypatch.setitem(source["run"].__globals__, "run_cli", forbidden)
    assert asyncio.run(source["run"](["--init", "--data-dir", str(tmp_path)])) == 0
    directory = tmp_path / "config"
    host = read_toml(directory / "host.toml")
    assert host["assembly"] == "org.aurora.adapter:assemblies/mcp/default_bot"
    assert not {"aurora_world", "aurora_world.configuration", "aurora_bot.cadence"} & set(host["plugins"])
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, load_plugins(enabled=host["plugins"]))
    for item in configuration_files(registry, directory):
        if item.path.exists():
            item.spec.schema.parse(read_toml(item.path))
    bot = read_toml(directory / "org.aurora.bot/config.toml")
    assert bot["input_budget"]["enabled"] and bot["input_budget"]["max_chars"] == 48000
    assert all(not bot[name]["enabled"] for name in ("context_view", "notes", "self_control", "archive", "actions"))
    servers = read_toml(directory / "org.aurora.adapter/mcp.toml")["servers"]
    assert set(servers) == {"terminal"}
    terminal = servers["terminal"]
    assert terminal["command"] == ["uvx", "--from", "terminal-mcp==0.4.7", "terminal-mcp"]
    assert len(terminal["tools"]["include"]) == 7
    assert set(terminal["tools"]["include"]) == set(terminal["tools"]["aliases"])
    profile = directory / "org.aurora.adapter/model/profiles.toml"
    profile.write_text("# 用户自有配置\n", encoding="utf-8")
    before = {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*.toml")}
    source["initialize"](tmp_path)
    assert before == {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*.toml")}
    assert not (tmp_path / "framework").exists()


def test_onboarding_roundtrip_restores_history_without_automatic_activation(tmp_path, monkeypatch):
    source = runpy.run_path(str(APPLICATION))
    source["initialize"](tmp_path)
    directory = tmp_path / "config"
    fixture = ROOT / "tests/fixtures/mcp_stdio_server.py"
    trace = tmp_path / "terminal"
    (directory / "org.aurora.adapter/mcp.toml").write_text(
        tomli_w.dumps(
            {
                "schema_version": 2,
                "servers": {
                    "terminal": {
                        "type": "local",
                        "command": [sys.executable, str(fixture), str(trace), "legacy"],
                        "tools": {"include": ["echo"], "aliases": {"echo": "terminal_list"}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    adapter = Id("dev.onboarding:adapters/fake")
    (directory / "org.aurora.adapter/model/profiles.toml").write_text(
        tomli_w.dumps({"primary": {"adapter": str(adapter), "model": "offline"}}),
        encoding="utf-8",
    )
    clients = []

    async def create_model(config, *, api_key=None):
        assert api_key is None

        def respond(request):
            assert [tool["name"] for tool in request["tools"]] == ["terminal_list"]
            assert request["messages"][0]["role"] == "system"
            if len(client.requests) == 1:
                return FakeReply(tool_calls=({"id": uuid4().hex, "name": "terminal_list", "arguments": {}},))
            assert request["messages"][-1]["role"] == "tool"
            result = json.loads(request["messages"][-1]["content"])
            assert result["status"] == "completed"
            assert Path(result["value"]["structuredContent"]["cwd"]) == ROOT
            return FakeReply(("环境检查完成",))

        client = FakeModel(respond)
        clients.append(client)
        return client

    plugin = Plugin(
        "onboarding_test",
        (
            RegistryEntry(
                adapter, "adapter", ModelAdapter("chat", create_model), "onboarding_test", register_to=ADAPTERS
            ),
        ),
    )

    async def offline_cli(arguments):
        return await run_cli(arguments, plugins=(plugin,))

    monkeypatch.setitem(source["run"].__globals__, "run_cli", offline_cli)
    monkeypatch.setitem(source["run"].__globals__, "load_dotenv", lambda *args, **kwargs: None)
    for text in ("检查环境", "继续配置"):
        assert asyncio.run(source["run"](["--data-dir", str(tmp_path), "--text", text])) == 0
    assert len(clients) == 2 and all(len(client.requests) == 2 for client in clients)
    snapshot = json.loads((tmp_path / "framework/ctx.json").read_text(encoding="utf-8"))
    context = next(item["value"] for item in snapshot["entries"] if item["id"] == "org.aurora.bot:state/messages")
    assert [m["content"] for m in context["messages"] if m["role"] == "user"] == ["检查环境", "继续配置"]
    assert context["pending"] is None
    assert (trace / "requests").read_text().splitlines().count("tools/call") == 2


def test_onboarding_requires_initialization_and_validates_access_before_host(tmp_path, monkeypatch):
    source = runpy.run_path(str(APPLICATION))
    with pytest.raises(SystemExit) as error:
        asyncio.run(source["run"](["--data-dir", str(tmp_path)]))
    assert error.value.code == 2
    source["initialize"](tmp_path)

    async def forbidden(*args, **kwargs):
        pytest.fail("无效的 API 访问配置不能启动宿主")

    monkeypatch.setitem(source["run"].__globals__, "run_cli", forbidden)
    monkeypatch.setitem(source["run"].__globals__, "load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="令牌"):
        asyncio.run(source["run"](["--data-dir", str(tmp_path), "--allowed-origin", "http://127.0.0.1:5173"]))
