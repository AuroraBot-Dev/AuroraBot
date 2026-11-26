"""真实本机进程验证两种协议、管道边界、环境隔离和子进程回收。"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import cast

import pytest
from aurora_adapter.mcp import CLIENT_STATUS, CONFIG_STATE, MCPClientError, MCPClients
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import install_lifecycle_slots
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_stdio_server.py"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 的 CMD/PATHEXT 命令发现")
def test_stdio_windows_resolves_script_extension_and_space_path(tmp_path):
    wrapper = tmp_path / "server wrapper.cmd"
    wrapper.write_text(f'@"{sys.executable}" "{FIXTURE}" "{tmp_path}" normal\n', encoding="utf-8")

    async def scenario():
        owner, ctx, _status = environment(tmp_path, command=[str(wrapper.with_suffix(""))])
        try:
            await owner.prepare()
            assert (await call(owner)).content
        finally:
            await owner.clean()
            ctx.close()
        await reaped(tmp_path)

    asyncio.run(scenario())


def alive(pid):
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def environment(root, mode="normal", protocol="legacy", **overrides):
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, load_plugins(enabled=["aurora_config", "aurora_adapter.mcp"]))
    ctx = Context(registry)
    owner = MCPClients(ctx, HookConnections(registry), workspace_root=root)
    server = {
        "type": "local",
        "command": [sys.executable, str(FIXTURE), str(root), mode, '空 格 "引号" $HOME'],
        "protocol": protocol,
        "timeout": {"startup": 5, "shutdown": 10},
        **overrides,
    }
    ctx.set(CONFIG_STATE, {"schema_version": 2, "servers": {"stdio": server}})
    owner.configure()

    def status():
        return cast(dict, ctx.get(CLIENT_STATUS, location={"owner": owner.instance_id, "connection_id": "stdio"}))

    return owner, ctx, status


async def call(owner):
    async with owner.connection("stdio") as client:
        return await client.session.send_request(
            CallToolRequest(params=CallToolRequestParams(name="echo", arguments={})), CallToolResult
        )


async def reaped(root):
    async with asyncio.timeout(5):
        while any(alive(int(path.read_text())) for name in ("pid", "child") if (path := root / name).exists()):
            await asyncio.sleep(0.02)


@pytest.mark.parametrize(
    "protocol,mode", [("legacy", "normal"), ("auto", "normal"), ("auto", "legacy"), ("2026-07-28", "normal")]
)
def test_stdio_protocol_cwd_environment_and_arguments(tmp_path, monkeypatch, protocol, mode):
    monkeypatch.setenv("PRIVATE_HOST_VALUE", "secret-host")
    monkeypatch.setenv("SOURCE_TOKEN", "secret-runtime")
    directory = tmp_path / "工作区 含空格"
    directory.mkdir()

    async def scenario():
        owner, ctx, status = environment(
            tmp_path, mode, protocol, cwd=directory.name, environment={"TEST_TOKEN": "{env:SOURCE_TOKEN}"}
        )
        try:
            await owner.prepare()
            result = await call(owner)
            assert result.structured_content == {
                "cwd": str(directory),
                "argument": '空 格 "引号" $HOME',
                "environment": "secret-runtime",
                "inherited": None,
            }
            assert status()["negotiated_protocol"] == (
                "2025-11-25" if protocol == "legacy" or mode == "legacy" else "2026-07-28"
            )
            methods = [attempt["method"] for attempt in status()["negotiation_attempts"]]
            assert methods == (
                ["initialize"]
                if protocol == "legacy"
                else ["server/discover", "initialize"]
                if mode == "legacy"
                else ["server/discover"]
            )
            assert "secret-runtime" not in json.dumps(status())
            assert ctx.snapshot(persistent_only=True).records == ()
        finally:
            await owner.clean()
            ctx.close()
        await reaped(tmp_path)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mode,code",
    [
        ("exit", "process_exited"),
        ("pollution", "invalid_protocol_response"),
        ("oversize", "stdout_limit"),
        ("incomplete", "stdout_incomplete"),
        ("hang", "connect_timeout"),
    ],
)
def test_stdio_startup_faults_are_bounded_and_private(tmp_path, caplog, mode, code):
    async def scenario():
        owner, ctx, status = environment(tmp_path, mode, timeout={"startup": 1, "shutdown": 10})
        try:
            with pytest.raises(MCPClientError, match=code):
                await owner.prepare()
            assert status()["phase"] == "failed"
            assert "secret-" not in json.dumps(status()) + caplog.text
        finally:
            await owner.clean()
            ctx.close()
        await reaped(tmp_path)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["normal", "tree", "children", "stderr"])
def test_stdio_close_reaps_descendants_and_stderr_cannot_block(tmp_path, mode, caplog):
    async def scenario():
        owner, ctx, status = environment(tmp_path, mode)
        try:
            await owner.prepare()
            assert (await call(owner)).content
        finally:
            await owner.clean()
            assert status()["phase"] == "closed"
            ctx.close()
        assert "secret-stderr" not in caplog.text
        await reaped(tmp_path)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"command": ["aurora-nonexistent-executable"]}, "process_start_failed"),
        ({"cwd": "missing-directory"}, "working_directory_invalid"),
        ({"environment": {"TOKEN": "{env:MCP_ABSENT}"}}, "credential_unavailable"),
    ],
)
def test_stdio_configuration_failures_do_not_spawn(tmp_path, overrides, code):
    async def scenario():
        owner, ctx, _status = environment(tmp_path, **overrides)
        try:
            with pytest.raises(MCPClientError, match=code):
                await owner.prepare()
            assert not (tmp_path / "pid").exists()
        finally:
            await owner.clean()
            ctx.close()

    asyncio.run(scenario())


def test_stdio_cancelled_startup_waits_for_owned_process_cleanup(tmp_path):
    async def scenario():
        owner, ctx, _status = environment(tmp_path, "hang")
        preparing = asyncio.create_task(owner.prepare())
        try:
            async with asyncio.timeout(5):
                while not (tmp_path / "pid").exists():
                    await asyncio.sleep(0.01)
            preparing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await preparing
        finally:
            await owner.clean()
            ctx.close()
        await reaped(tmp_path)
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("aurora-mcp:")]

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [True, False])
def test_stdio_close_wait_can_be_cancelled_or_expire_then_retried(tmp_path, cancel):
    async def scenario():
        owner, ctx, status = environment(tmp_path, "tree", timeout={"shutdown": 0.1 if not cancel else 10})
        await owner.prepare()
        closing = asyncio.create_task(owner.clean())
        try:
            if cancel:
                await asyncio.sleep(0.05)
                closing.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await closing
            else:
                with pytest.raises(TimeoutError):
                    await closing
            async with asyncio.timeout(8):
                while True:
                    try:
                        await owner.clean()
                    except TimeoutError:
                        continue
                    break
            assert status()["phase"] == "closed"
            assert (tmp_path / "requests").read_text().splitlines().count("initialize") == 1
        finally:
            ctx.close()
        await reaped(tmp_path)

    asyncio.run(scenario())


def test_stdio_process_exit_after_sending_tool_never_replays(tmp_path):
    async def scenario():
        owner, ctx, status = environment(tmp_path, "call_exit")
        try:
            await owner.prepare()
            with pytest.raises(MCPClientError, match="request_failed"):
                await call(owner)
            async with asyncio.timeout(5):
                while status()["phase"] != "failed":
                    await asyncio.sleep(0.01)
            assert status()["error"] == "process_exited"
            with pytest.raises(MCPClientError, match="not_accepting"):
                await call(owner)
            assert (tmp_path / "requests").read_text().splitlines().count("tools/call") == 1
        finally:
            await owner.clean()
            ctx.close()
        await reaped(tmp_path)

    asyncio.run(scenario())


def test_stdio_exited_parent_with_inherited_pipe_cannot_hold_session_open(tmp_path):
    async def scenario():
        owner, ctx, status = environment(tmp_path, "orphan")
        try:
            await owner.prepare()
            async with asyncio.timeout(5):
                while status()["phase"] != "failed":
                    await asyncio.sleep(0.01)
            assert status()["error"] == "process_exited"
        finally:
            await owner.clean()
            ctx.close()
        await reaped(tmp_path)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["normal", "pollution"])
def test_stdio_cleanup_failure_is_reported_even_during_failed_handshake(tmp_path, monkeypatch, mode):
    from aurora_adapter.mcp import stdio

    close = stdio._close

    async def failing_close(process):
        await close(process)
        raise OSError("secret-close-error")

    monkeypatch.setattr(stdio, "_close", failing_close)

    async def scenario():
        owner, ctx, status = environment(tmp_path, mode)
        try:
            if mode == "normal":
                await owner.prepare()
            else:
                with pytest.raises(MCPClientError, match="close_failed"):
                    await owner.prepare()
            with pytest.raises(MCPClientError, match="close_failed"):
                await owner.clean()
            assert status()["error"] == "close_failed"
        finally:
            ctx.close()
        await reaped(tmp_path)

    asyncio.run(scenario())
