"""有界 stdio 管道；复用 SDK 消息类型、基础环境及平台进程树管理。"""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import anyio
from anyio.abc import Process
from anyio.streams.buffered import BufferedByteReceiveStream
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.client.stdio import StdioServerParameters, get_default_environment
from mcp.os.posix.utilities import terminate_posix_process_tree
from mcp.os.win32.utilities import (
    ServerProcess,
    create_windows_process,
    get_windows_executable_command,
    terminate_windows_process_tree,
)
from mcp.shared.message import SessionMessage
from mcp.types import jsonrpc_message_adapter

from .credentials import resolve_values
from .errors import MCPClientError
from .negotiation import Negotiation

MAX_MESSAGE_BYTES = 4 * 1024 * 1024


def parameters(config: dict, root: Path | None, resolve_env: Callable[[str], str | None]) -> StdioServerParameters:
    """仅在 prepare 解析环境及工作区路径；命令保持参数数组，不经 shell 拼接。"""
    location = f"servers.{config['connection_id']}"
    if root is None:
        raise MCPClientError("workspace_required", location=location)
    try:
        workspace = root.resolve(strict=True)
        cwd = (workspace / config.get("cwd", ".")).resolve(strict=True)
        if not workspace.is_dir() or not cwd.is_dir():
            raise OSError
    except (OSError, RuntimeError):
        raise MCPClientError("working_directory_invalid", location=f"{location}.cwd") from None
    try:
        environment = resolve_values(config.get("environment", {}), resolve_env, headers=False)
    except ValueError as error:
        raise MCPClientError("credential_unavailable", location=f"{location}.environment.{error}") from None
    return StdioServerParameters(command=config["command"][0], args=config["command"][1:], cwd=cwd, env=environment)


async def _spawn(server: StdioServerParameters) -> ServerProcess:
    environment = get_default_environment() | (server.env or {})
    try:
        with open(os.devnull, "w", encoding="utf-8") as stderr:  # noqa: ASYNC230 — 固定空设备，无文件读取或磁盘写入。
            if sys.platform == "win32":
                command = await anyio.to_thread.run_sync(get_windows_executable_command, server.command)
                return await create_windows_process(command, server.args, environment, stderr, server.cwd)
            return await anyio.open_process(
                [server.command, *server.args], env=environment, stderr=stderr, cwd=server.cwd, start_new_session=True
            )
    except (OSError, ValueError):
        raise MCPClientError("process_start_failed") from None


async def _wait_exit(process: ServerProcess, seconds: float) -> bool:
    """轮询根进程；后代继承管道不能使已退出的根进程看起来仍在运行。"""
    with anyio.move_on_after(seconds):
        while process.returncode is None:
            await anyio.sleep(0.01)
        return True
    return False


async def _close(process: ServerProcess) -> None:
    """关闭输入后限时等待，始终回收进程树，包括根进程已经正常退出的情形。"""
    with anyio.CancelScope(shield=True):
        assert process.stdin is not None and process.stdout is not None
        with suppress(OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            await process.stdin.aclose()
        await _wait_exit(process, 2)
        if sys.platform == "win32":
            await terminate_windows_process_tree(process)
        else:
            assert isinstance(process, Process)
            await terminate_posix_process_tree(process, 2)
        exited = await _wait_exit(process, 2)
        with anyio.move_on_after(2) as scope:
            await process.stdout.aclose()
            if isinstance(process, Process):
                await process.aclose()
        if not exited or scope.cancelled_caught:
            raise MCPClientError("close_failed")


async def _finish(process: ServerProcess) -> None:
    """原生 asyncio 取消和 anyio 取消均不能中断已经开始的有界进程回收。"""
    try:
        with anyio.CancelScope(shield=True):
            closing = asyncio.create_task(_close(process), name="aurora-mcp:reap")
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                await asyncio.shield(closing)
                raise
    except Exception:  # noqa: BLE001 — 清理异常优先报告，避免被原始握手或管道故障掩盖。
        raise MCPClientError("close_failed") from None


@asynccontextmanager
async def stdio_transport(
    server: StdioServerParameters, state: Negotiation
) -> AsyncIterator[
    tuple[MemoryObjectReceiveStream[SessionMessage | Exception], MemoryObjectSendStream[SessionMessage]]
]:
    """传输只处理分帧和所有权；协议协商、会话及工具调用仍由 SDK 执行。"""
    spawning = asyncio.create_task(_spawn(server), name="aurora-mcp:spawn")
    try:
        process = await asyncio.shield(spawning)
    except asyncio.CancelledError:
        try:
            process = await asyncio.shield(spawning)
        except MCPClientError:
            pass
        else:
            await _finish(process)
        raise
    incoming, read = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write, outgoing = anyio.create_memory_object_stream[SessionMessage](0)
    attempts: dict[str | int, dict] = {}
    closing = False

    async def receive() -> None:
        assert process.stdout is not None
        stdout = BufferedByteReceiveStream(process.stdout)
        try:
            async with incoming:
                while True:
                    line = await stdout.receive_until(b"\n", MAX_MESSAGE_BYTES)
                    if len(line) > MAX_MESSAGE_BYTES:
                        raise MCPClientError("stdout_limit")
                    try:
                        message = jsonrpc_message_adapter.validate_json(line, by_name=False)
                    except ValueError:
                        raise MCPClientError("invalid_protocol_response") from None
                    payload = message.model_dump(by_alias=True, exclude_unset=True)
                    identity = payload.get("id")
                    attempt = (
                        attempts.pop(identity, None)
                        if isinstance(identity, (int, str)) and "method" not in payload
                        else None
                    )
                    if attempt is not None:
                        state.response(attempt, payload)
                    await incoming.send(SessionMessage(message))
        except anyio.DelimiterNotFound:
            raise MCPClientError("stdout_limit") from None
        except anyio.IncompleteRead:
            if not closing:
                raise MCPClientError("stdout_incomplete" if stdout.buffer else "process_exited") from None
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            if not closing:
                raise MCPClientError("transport_failed") from None

    async def send() -> None:
        assert process.stdin is not None
        try:
            async with outgoing:
                async for envelope in outgoing:
                    payload = envelope.message.model_dump(by_alias=True, exclude_unset=True)
                    attempt = state.request(payload.get("method", ""))
                    if attempt is not None:
                        attempts[payload["id"]] = attempt
                    data = envelope.message.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8")
                    if len(data) > MAX_MESSAGE_BYTES:
                        raise MCPClientError("stdin_limit")
                    await process.stdin.send(data + b"\n")
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            if not closing:
                raise MCPClientError("transport_failed") from None

    async def watch() -> None:
        while process.returncode is None:
            await anyio.sleep(0.02)
        if not closing:
            raise MCPClientError("process_exited")

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(receive)
        tasks.start_soon(send)
        tasks.start_soon(watch)
        try:
            yield read, write
        finally:
            closing = True
            try:
                await _finish(process)
            finally:
                read.close()
                write.close()
                incoming.close()
                outgoing.close()
                tasks.cancel_scope.cancel()
