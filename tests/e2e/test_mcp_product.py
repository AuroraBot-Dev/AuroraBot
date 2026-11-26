"""正式 CLI/API 宿主使用 MCP 预设与假模型，不手工拼装客户端或工具桥。"""

import asyncio
import json
import runpy
import socket
import sys
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path

import httpx
import pytest
import tomli_w
import uvicorn
from aurora_adapter.mcp.catalog import automatic_name
from aurora_adapter.mcp.preset import initialize
from aurora_adapter.model.config import ADAPTERS, ModelAdapter
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_cli.commander import run_cli
from aurora_core import Id
from aurora_core.discovery import Plugin
from aurora_core.registry import RegistryEntry

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_tools_roundtrip.py"
ADAPTER = Id("dev.product:adapters/fake")


@asynccontextmanager
async def service(root, transport):
    calls = []
    if transport == "local":
        yield (
            {"type": "local", "command": [sys.executable, str(FIXTURE), str(root), "--stdio-server"]},
            lambda: [json.loads(line) for line in (root / "calls.jsonl").read_text(encoding="utf-8").splitlines()],
        )
        return
    create = runpy.run_path(str(FIXTURE))["echo_service"]
    server = uvicorn.Server(
        uvicorn.Config(create(calls.append).streamable_http_app(), log_level="critical", lifespan="on")
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("测试 MCP 服务启动失败")
                await asyncio.sleep(0.01)
        yield {"type": "remote", "url": f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"}, lambda: calls
    finally:
        server.should_exit = True
        await task
        listener.close()


def seed(root, server, *, explicit=False):
    assert initialize(root, api=True, output=StringIO()) == 0
    name = automatic_name("sample", "echo")
    values = {
        "org.aurora.adapter/mcp.toml": {"schema_version": 2, "servers": {"sample": {**server, "protocol": "auto"}}},
        "org.aurora.adapter/model/profiles.toml": {"test": {"adapter": str(ADAPTER), "model": "fake"}},
        "org.aurora.adapter/model/bindings.toml": {"reasoning": "test"},
        "org.aurora.bot/config.toml": {
            "instance_id": "main",
            "model_role": "reasoning",
            "streaming": False,
            "tools": [{"tool": f"org.aurora.adapter:tools/mcp/{name}", "instance_id": "preserved"}] if explicit else [],
        },
    }
    for relative, value in values.items():
        (root / "config" / relative).write_text(tomli_w.dumps(value), encoding="utf-8")
    return name


def fake_plugin(name, clients):
    async def factory(config, *, api_key=None):
        def reply(request):
            assert [tool["name"] for tool in request["tools"]] == [name]
            if any(message["role"] == "tool" for message in request["messages"]):
                return FakeReply(("完成",))
            return FakeReply(tool_calls=({"id": "echo-call", "name": name, "arguments": {"text": "你好"}},))

        client = FakeModel(reply)
        clients.append(client)
        return client

    return Plugin(
        "test.product",
        (RegistryEntry(ADAPTER, "adapter", ModelAdapter("chat", factory), "test.product", register_to=ADAPTERS),),
    )


@pytest.mark.parametrize("transport,explicit", [("remote", True), ("local", False)])
def test_product_preset_runs_via_cli_and_preserves_original_configuration(tmp_path, transport, explicit):
    async def scenario():
        async with service(tmp_path, transport) as (declaration, calls):
            name = seed(tmp_path, declaration, explicit=explicit)
            before = {path: path.read_bytes() for path in (tmp_path / "config").rglob("*.toml")}
            clients = []
            output = StringIO()
            assert (
                await run_cli(
                    [
                        "--root",
                        str(tmp_path),
                        "-d",
                        str(tmp_path),
                        "org.aurora.bot:commands/run/submit",
                        "回显",
                        "--instance-id",
                        "main",
                    ],
                    plugins=[fake_plugin(name, clients)],
                    output=output,
                )
                == 0
            )
            assert json.loads(output.getvalue().splitlines()[-1])["status"] == "completed"
            assert calls() == ["你好"]
            assert len(clients) == 1 and clients[0].closed
            assert all(path.read_bytes() == content for path, content in before.items())
            assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("aurora-mcp:")]

    asyncio.run(scenario())


@pytest.mark.parametrize("transport", ["remote", "local"])
def test_product_preset_runs_via_formal_api_host(tmp_path, transport):
    async def scenario():
        async with service(tmp_path, transport) as (declaration, calls):
            name = seed(tmp_path, declaration)
            clients = []
            with socket.socket() as available:
                available.bind(("127.0.0.1", 0))
                port = available.getsockname()[1]
            host = asyncio.create_task(
                run_cli(
                    [
                        "--root",
                        str(tmp_path),
                        "-d",
                        str(tmp_path),
                        "serve",
                        "--port",
                        str(port),
                        "--endpoints",
                        '["org.aurora.bot:endpoints/conversation"]',
                    ],
                    plugins=[fake_plugin(name, clients)],
                    output=StringIO(),
                )
            )
            try:
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as http:
                    async with asyncio.timeout(15):
                        while True:
                            if host.done():
                                await host
                                raise RuntimeError("API 宿主提前结束")
                            try:
                                response = await http.post("/conversation/info", json={})
                                assert response.status_code == 200, response.text
                                break
                            except httpx.TransportError:
                                pass
                            await asyncio.sleep(0.02)
                        info = response.json()["result"]
                        message = {
                            "session_id": info["session_id"],
                            "instance_id": "main",
                            "request_id": "one",
                            "text": "回显",
                        }
                        response = await http.post("/conversation/submit", json=message)
                        assert response.status_code == 200, response.text
                        while True:
                            result = await http.post(
                                "/conversation/query",
                                json={key: value for key, value in message.items() if key != "text"},
                            )
                            assert result.status_code == 200, result.text
                            status = result.json()["result"]["run_status"]
                            assert status in ("pending", "completed"), result.text
                            if status == "completed":
                                break
                            await asyncio.sleep(0.01)
                    assert calls() == ["你好"]
            finally:
                host.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await host
            assert len(clients) == 1 and clients[0].closed
            assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("aurora-mcp:")]

    asyncio.run(scenario())
