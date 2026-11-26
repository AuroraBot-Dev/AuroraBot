"""真实进程验证常驻宿主、远程命令、订阅中断与重启恢复。"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import pytest

CONFIG = "org.aurora.cli:state/config"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "api_cli_process.py"


async def start_cli(*args, cwd=None, stop_file=None):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "COLUMNS": "160"}
    command = [sys.executable, "-m", "aurora_cli"]
    if stop_file is not None:
        env["AURORA_TEST_STOP_FILE"] = str(stop_file)
        command = [sys.executable, str(FIXTURE)]
    return await asyncio.create_subprocess_exec(
        *command,
        *map(str, args),
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def wait_message(process, marker):
    async with asyncio.timeout(10):
        while True:
            line = (await process.stderr.readline()).decode("utf-8")
            if not line:
                raise AssertionError(f"CLI 在 {marker} 前退出：{process.returncode}")
            if marker in line:
                return line


async def command(*args, cwd=None):
    process = await start_cli(*args, cwd=cwd)
    try:
        output, error = await asyncio.wait_for(process.communicate(), 10)
        assert process.returncode == 0, error.decode("utf-8")
        return json.loads(output)
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


def test_remote_watch_and_commands_share_one_host_with_transient_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("AURORA_TEST_ACCESS", "test-cli-access-token-123456789012")
    authentication = ["--connect-token-env", "AURORA_TEST_ACCESS"]
    server_authentication = ["--token-env", "AURORA_TEST_ACCESS"]

    async def scenario():
        data = tmp_path / "host-data"
        client_dir = tmp_path / "client"
        client_dir.mkdir()
        host_stop = tmp_path / "stop-host"
        watch_stop = tmp_path / "stop-watch"
        host = await start_cli(
            "-d", data, "--config", '{"count":0}', "serve", "--port", "0", *server_authentication, stop_file=host_stop
        )
        processes = [host]
        try:
            line = await wait_message(host, "ctx API 已监听")
            match = re.search(r"http://127\.0\.0\.1:\d+", line)
            assert match is not None, line
            url = match.group()
            watcher = await start_cli(
                "--connect", url, *authentication, "ctx", "watch", cwd=client_dir, stop_file=watch_stop
            )
            processes.append(watcher)
            await wait_message(watcher, "正在观察")
            assert watcher.stdout is not None
            assert (
                await command("--connect", url, *authentication, "ctx", "set", CONFIG, '{"count":1}', cwd=client_dir)
                is None
            )
            event = json.loads(await asyncio.wait_for(watcher.stdout.readline(), 5))
            assert event["previous"] == {"count": 0}
            assert event["value"] == {"count": 1}
            assert event["action"] == "set"
            assert await command("--connect", url, *authentication, "ctx/get", CONFIG, cwd=client_dir) == {"count": 1}
            assert await command("--connect", url, *authentication, "ctx/list", cwd=client_dir) == [
                {"id": CONFIG, "location": {}}
            ]
            assert await command("--connect", url, *authentication, "ctx/delete", CONFIG, cwd=client_dir) is True
            deleted = json.loads(await asyncio.wait_for(watcher.stdout.readline(), 5))
            assert deleted["action"] == "delete"
            assert deleted["revision"] > event["revision"]

            watch_stop.touch()
            await asyncio.wait_for(watcher.communicate(), 5)
            assert watcher.returncode == 130
            assert host.returncode is None
            await command("--connect", url, *authentication, "ctx/set", CONFIG, '{"count":2}', cwd=client_dir)

            watcher = await start_cli("--connect", url, *authentication, "ctx/watch", cwd=client_dir)
            processes.append(watcher)
            await wait_message(watcher, "正在观察")
            host_stop.touch()
            _, error = await asyncio.wait_for(host.communicate(), 5)
            assert host.returncode == 130, error.decode("utf-8")
            _, error = await asyncio.wait_for(watcher.communicate(), 5)
            assert watcher.returncode == 1
            assert "订阅连接已关闭" in error.decode("utf-8")
            assert list(client_dir.iterdir()) == []
            assert await command("-d", data, "ctx/get", CONFIG) == {}
        finally:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                await process.communicate()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "arguments",
    [
        ["--data-dir", "unused", "ctx/list"],
        ["serve"],
    ],
)
def test_remote_mode_rejects_local_host_options_without_creating_storage(tmp_path, arguments):
    async def scenario():
        process = await start_cli("--connect", "http://127.0.0.1:1", *arguments, cwd=tmp_path)
        _, error = await asyncio.wait_for(process.communicate(), 5)
        assert process.returncode == 2, error.decode("utf-8")
        assert "--connect" in error.decode("utf-8")
        assert list(tmp_path.iterdir()) == []

    asyncio.run(scenario())


def test_connection_failure_does_not_fall_back_to_local_host(tmp_path):
    async def scenario():
        process = await start_cli("--connect", "http://127.0.0.1:0", "ctx/list", cwd=tmp_path)
        _, error = await asyncio.wait_for(process.communicate(), 5)
        assert process.returncode == 1
        assert error
        assert list(tmp_path.iterdir()) == []

    asyncio.run(scenario())
