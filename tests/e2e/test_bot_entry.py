"""根入口的环境解析、完整装配、API 权限与收尾使用隔离目录和假模型验证。"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from io import StringIO

import httpx
import pytest
import tomli_w
from aurora_cli.commander import run_cli
from test_mcp_product import fake_plugin, seed, service

from scripts import bot

TOKEN = "test-root-product-token-1234567890"
TOKEN_ENV = "AURORA_TEST_ROOT_TOKEN"


def test_help_does_not_load_environment_or_start_host(tmp_path):
    result = subprocess.run(
        [sys.executable, str(bot.ROOT / "scripts/bot.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert b"--env-file" in result.stdout
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("override", [False, True])
def test_default_paths_are_project_relative_and_process_environment_wins(tmp_path, monkeypatch, override):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(f"{TOKEN_ENV}={TOKEN}\n", encoding="utf-8")
    monkeypatch.setattr(bot, "ROOT", project)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    expected = "process-root-product-token-1234567890" if override else TOKEN
    if override:
        monkeypatch.setenv(TOKEN_ENV, expected)

    async def capture(argv):
        assert os.environ[TOKEN_ENV] == expected
        assert argv[argv.index("--root") + 1] == str(project)
        assert argv[argv.index("--data-dir") + 1] == str(project / "data")
        assert expected not in json.dumps(argv)
        return 0

    monkeypatch.setattr(bot, "run_cli", capture)
    assert asyncio.run(bot.run(["--token-env", TOKEN_ENV])) == 0
    assert not (project / "data").exists()


@pytest.mark.parametrize("value", [None, "bad-token"])
def test_invalid_token_fails_before_starting_resources(tmp_path, monkeypatch, value):
    monkeypatch.setattr(bot, "ROOT", tmp_path)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    if value is not None:
        monkeypatch.setenv(TOKEN_ENV, value)
    with pytest.raises(ValueError, match="访问令牌"):
        asyncio.run(bot.run(["--token-env", TOKEN_ENV]))
    assert not list(tmp_path.iterdir())


def test_explicit_missing_environment_file_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    with pytest.raises(FileNotFoundError, match="环境文件不存在"):
        asyncio.run(bot.run(["--env-file", str(tmp_path / "missing.env"), "--token-env", TOKEN_ENV]))


@pytest.mark.parametrize(("edit_config", "archived_event"), [(False, False), (True, True)])
def test_full_product_from_incomplete_host_config(tmp_path, monkeypatch, edit_config, archived_event):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    async def scenario():
        async with service(tmp_path, "local") as (server, calls):
            name = seed(tmp_path, server)
            host_path = tmp_path / "config/host.toml"
            host_path.write_text(
                'plugins = ["test.product"]\nassembly = "org.aurora.bot:assemblies/default"\n', encoding="utf-8"
            )
            world = tmp_path / "config/org.aurora.world/config.toml"
            world.parent.mkdir(exist_ok=True)
            sources = [{"source": "org.aurora.world:sources/environment/time", "source_id": "clock"}]
            if archived_event:
                sources.append(
                    {
                        "source": "org.aurora.world:sources/environment/time",
                        "source_id": "pulse",
                        "presentation": "events",
                    }
                )
                (tmp_path / "config/org.aurora.bot/cadence.toml").write_text("", encoding="utf-8")
            world.write_text(tomli_w.dumps({"sources": sources}), encoding="utf-8")
            before = {path: path.read_bytes() for path in (tmp_path / "config").rglob("*.toml")}
            clients = []

            async def with_fake_model(argv):
                return await run_cli(argv, plugins=[fake_plugin(name, clients)], output=StringIO())

            monkeypatch.setattr(bot, "run_cli", with_fake_model)
            with socket.socket() as available:
                available.bind(("127.0.0.1", 0))
                port = available.getsockname()[1]
            task = asyncio.create_task(
                bot.run(
                    [
                        "--data-dir",
                        str(tmp_path),
                        "--env-file",
                        str(env_file),
                        "--token-env",
                        TOKEN_ENV,
                        "--port",
                        str(port),
                        *(["--edit-config"] if edit_config else []),
                    ]
                )
            )
            headers = {"Origin": "http://127.0.0.1:5173", "Authorization": f"Bearer {TOKEN}"}
            try:
                async with (
                    asyncio.timeout(20),
                    httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=headers, trust_env=False) as http,
                ):
                    while True:
                        if task.done():
                            await task
                            pytest.fail("根入口提前退出")
                        try:
                            response = await http.post("/conversation/info", json={})
                            assert response.status_code == 200, response.text
                            break
                        except httpx.TransportError:
                            await asyncio.sleep(0.02)
                    info = response.json()["result"]
                    assert len(clients) == 1
                    while True:
                        state = await http.post(
                            "/ctx/get", json={"key": str(bot.RUN), "location": {"instance_id": "main"}}
                        )
                        assert state.status_code == 200
                        if state.json()["result"]["status"] == "completed":
                            break
                        await asyncio.sleep(0.02)
                    assert clients[0].requests
                    assert (await http.post("/configuration/list", json={})).status_code == (
                        200 if edit_config else 404
                    )
                    for key in bot.READ_ONLY_KEYS:
                        response = await http.post("/ctx/list", json={"key": str(key)})
                        assert response.status_code == 200, response.text
                    environment = await http.post("/ctx/list", json={"key": str(bot.ENVIRONMENT)})
                    assert "clock" in environment.text
                    mcp = await http.post("/ctx/list", json={"key": str(bot.CLIENT_STATUS)})
                    assert "sample" in mcp.text
                    denied = await http.post("/ctx/set", json={"key": str(bot.WORK), "value": {}})
                    assert denied.status_code == 403
                    unauthorized = await http.post(
                        "/conversation/info", json={}, headers={"Authorization": "Bearer bad"}
                    )
                    assert unauthorized.status_code == 401
                    message = {
                        "session_id": info["session_id"],
                        "instance_id": "main",
                        "request_id": "one",
                        "text": "回显",
                    }
                    assert (await http.post("/conversation/submit", json=message)).status_code == 200
                    while True:
                        result = await http.post(
                            "/conversation/query", json={k: v for k, v in message.items() if k != "text"}
                        )
                        if result.json()["result"]["run_status"] == "completed":
                            break
                        await asyncio.sleep(0.02)
                    assert calls() == ["你好"]
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert clients[0].closed
            assert all(path.read_bytes() == content for path, content in before.items())
            assert (tmp_path / "config/org.aurora.bot/cadence.toml").is_file()
            assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("aurora-mcp:")]
            snapshot = (tmp_path / "framework/ctx.json").read_text(encoding="utf-8")
            assert TOKEN not in snapshot
            assert "org.aurora.bot:state/cadence" in snapshot

    asyncio.run(scenario())
