"""跨进程验证常驻示例的 CLI、bot 循环、控制组件和关闭恢复。"""

import asyncio
import json
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from aiohttp import ClientSession
from aurora_api.client import CtxClient, RemoteError

EXAMPLE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "runtime_apps" / "live_workshop" / "main.py"
PREFIX = "dev.example.workshop:state/"
LAUNCHER = """
import asyncio
import runpy
import signal
import sys
from pathlib import Path

source_path, stop_path, *arguments = sys.argv[1:]
sys.path.insert(0, str(Path(source_path).parent))
source = runpy.run_path(source_path)
original = source['run']

async def interrupt():
    while not Path(stop_path).exists():
        await asyncio.sleep(0.02)
    signal.raise_signal(signal.SIGINT)

async def run():
    monitor = asyncio.create_task(interrupt())
    try:
        return await original()
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)

source['main'].__globals__['run'] = run
sys.argv = [source_path, *arguments]
raise SystemExit(source['main']())
"""


@asynccontextmanager
async def workshop(root, initial=None):
    stop = root / "interrupt"
    stop.unlink(missing_ok=True)
    options = [] if initial is None else ["--config", json.dumps(initial)]
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        LAUNCHER,
        str(EXAMPLE),
        str(stop),
        "-d",
        str(root / "data"),
        *options,
        "serve",
        "--port",
        "0",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "COLUMNS": "180"},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stderr is not None
    drain = None
    startup = []
    try:
        async with asyncio.timeout(10):
            while True:
                line = await process.stderr.readline()
                if not line:
                    raise AssertionError(b"".join(startup).decode("utf-8"))
                startup.append(line)
                match = re.search(rb"http://127\.0\.0\.1:\d+", line)
                if match:
                    break
        drain = asyncio.create_task(process.stderr.read())
        async with CtxClient(match.group().decode()) as client:
            yield client, process, stop
        stop.touch()
        await asyncio.wait_for(process.wait(), 8)
        errors = (await drain).decode("utf-8")
        assert process.returncode == 130, errors
        assert "Task exception was never retrieved" not in errors
        assert "生命周期停止失败" not in errors
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        if drain is not None:
            await drain


async def state(client, key, **filters):
    value = await client.request("get", key=key, **filters)
    assert isinstance(value, dict)
    return value


async def until(client, key, predicate, **filters):
    async with asyncio.timeout(20):
        while True:
            value = await state(client, key, **filters)
            if predicate(value):
                return value
            await asyncio.sleep(0.03)


async def cli_set(client, key, value):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "aurora_cli",
        "--connect",
        client.url,
        "ctx",
        "set",
        key,
        json.dumps(value),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    output, error = await asyncio.wait_for(process.communicate(), 10)
    assert process.returncode == 0, error.decode("utf-8")
    assert json.loads(output) is None


async def conversation(client, action, data):
    async with ClientSession() as session, session.post(client.url + "/conversation/" + action, json=data) as response:
        body = await response.json()
        assert response.status == 200, body
        return body["result"]


async def submit(client, value):
    info = await conversation(client, "info", {})
    return await conversation(
        client,
        "submit",
        {
            "session_id": info["session_id"],
            "instance_id": "workshop",
            "request_id": uuid4().hex,
            "text": value if isinstance(value, str) else json.dumps(value),
        },
    )


def test_interrupt_cancels_active_tool_and_restores_pending_observation(tmp_path):
    async def scenario():
        async with workshop(tmp_path, {"automatic": False, "delay": 1}) as (client, _, _):
            await submit(client, {"text": "中断任务", "steps": 20})
            await until(
                client,
                "org.aurora.bot:state/run",
                lambda value: value.get("phase") == "act",
                location={"instance_id": "workshop"},
            )
        snapshot = json.loads((tmp_path / "data" / "framework" / "ctx.json").read_text(encoding="utf-8"))
        entries = snapshot["entries"]
        runtime = next(item["value"] for item in entries if item["id"] == "org.aurora.bot:state/run")
        assert runtime["status"] == "cancelled"
        assert not any(item["id"] in (PREFIX + "pipeline", "org.aurora.control:state/control") for item in entries)
        async with workshop(tmp_path) as (client, _, _):
            await cli_set(client, PREFIX + "settings", {"automatic": False, "delay": 0})
            await submit(client, {"text": "恢复后的任务", "steps": 1})
            reports = await until(client, PREFIX + "reports", lambda value: value["total"] == 2)
            assert [item["result"]["status"] for item in reports["recent"]] == ["cancelled", "completed"]

    asyncio.run(scenario())


def test_world_and_direct_input_share_run_and_restore_without_replay(tmp_path):
    async def scenario():
        location = {"instance_id": "workshop"}
        async with workshop(tmp_path, {"interval": 60, "steps": 10, "delay": 0.2}) as (client, _, _):
            active = await until(
                client, "org.aurora.bot:state/run", lambda value: value.get("phase") == "act", location=location
            )
            await client.request("set", key=PREFIX + "settings", value={"automatic": False, "delay": 0})
            receipt = await submit(client, "世界巡检期间的直接交流")
            assert receipt["run_id"] == active["run_id"]
            checkpoint = await state(client, "org.aurora.bot:state/cadence", location=location)
            assert len(checkpoint["receipts"]) == 1
            assert checkpoint["receipts"][0]["run_id"] == receipt["run_id"]
            reports = await until(client, PREFIX + "reports", lambda value: value["total"] == 2)
            assert {item["text"] for item in reports["recent"]} == {"自动巡检 #1", "世界巡检期间的直接交流"}
            await until(client, PREFIX + "status", lambda value: value["status"] == "completed")
            query = await conversation(
                client, "query", {key: receipt[key] for key in ("session_id", "instance_id", "request_id")}
            )
            assert query["run_status"] == "completed"
            context = await state(client, "org.aurora.bot:state/messages", location=location)
            calls = {call["id"] for message in context["messages"] for call in message.get("tool_calls", [])}
            assert all(message["tool_call_id"] in calls for message in context["messages"] if message["role"] == "tool")
            for key in ("org.aurora.world:state/records", "org.aurora.bot:state/cadence"):
                for action in ("set", "delete"):
                    with pytest.raises(RemoteError, match="forbidden"):
                        await client.request(
                            action,
                            key=key,
                            location=location if "cadence" in key else {},
                            **({"value": {}} if action == "set" else {}),
                        )
        async with workshop(tmp_path) as (client, _, _):
            world = await state(client, PREFIX + "world")
            await client.request(
                "set", key=PREFIX + "settings", value={"automatic": False, "interval": 0.5, "delay": 0}
            )
            await until(client, PREFIX + "world", lambda value: value["tick"] > world["tick"])
            assert (await state(client, PREFIX + "reports"))["total"] == 2
            assert await state(client, "org.aurora.bot:state/cadence", location=location) == checkpoint
            await submit(client, "重启后的新交流")
            await until(client, PREFIX + "reports", lambda value: value["total"] == 3)

    asyncio.run(scenario())
