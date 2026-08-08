"""MCP Server 进程生命周期管理器。

负责本地 stdio MCP Server 的启动、停止、重启和健康检查。
工具能力由 MCP Client 通过 tools/list 动态发现。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from src.utils import get_logger

if TYPE_CHECKING:
    from src.platform.mcp.server_spec import MCPServerSpec

logger = get_logger("MCPServerKit")
_STDOUT_LIMIT = 16 * 1024 * 1024
_INHERITED_ENV = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "USERPROFILE",
        "WINDIR",
        "XDG_CACHE_HOME",
    }
)


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    NO_COMMAND = "Server {key} 没有配置启动命令"
    START_FAILED_IO = "启动 Server {key} 失败: 命令或临时目录不可用 {command} — {error}"
    START_FAILED_OS = "启动 Server {key} 失败: {error}"
    NOT_RUNNING = "Server {key} 不在运行中，无法重启"


def _ensure_tempdir() -> Path:
    """确保有一个可用的临时目录。

    在沙箱/受限环境中，系统 TEMP 可能不可写（``os.access`` 返回 True 但
    实际创建文件失败），导致 ``asyncio.create_subprocess_exec`` 在 Windows
    上创建命名管道时失败。此函数检测并回退到当前工作目录。

    Returns:
        可用的临时目录路径。
    """
    try:
        # 尝试在默认 temp 目录创建文件验证可用性
        d = Path(tempfile.gettempdir())
        test_file = d / f"_aurora_tmp_test_{os.getpid()}.tmp"
        test_file.write_text("")
        test_file.unlink()
    except (OSError, FileNotFoundError):
        pass
    else:
        return d

    # 回退到 CWD（已验证可写）
    cwd = Path.cwd()
    logger.debug("系统 TEMP 不可写，回退使用 CWD: %s", cwd)
    tempfile.tempdir = str(cwd)
    return cwd


def _subprocess_environment(extra: dict[str, str], temp_dir: Path) -> dict[str, str]:
    """只继承进程启动所需环境，并叠加 App 显式授权的变量。"""
    environment = {name: os.environ[name] for name in _INHERITED_ENV if name in os.environ}
    environment.update({"TEMP": str(temp_dir), "TMP": str(temp_dir), "TMPDIR": str(temp_dir)})
    environment.update(extra)
    return environment


@dataclass(slots=True)
class ServerProcess:
    """运行的 MCP Server 进程信息。"""

    spec: MCPServerSpec
    process: asyncio.subprocess.Process
    health_task: asyncio.Task[None] | None = None
    stderr_task: asyncio.Task[None] | None = None


class MCPServerKit:
    """MCP Server 进程生命周期管理器。

    Usage::

        kit = MCPServerKit()
        await kit.start_all(specs)
        ...
        await kit.stop_all()
    """

    def __init__(self, *, terminal_logs: bool = True) -> None:
        self._processes: dict[str, ServerProcess] = {}
        self._terminal_logs = terminal_logs

    @property
    def processes(self) -> dict[str, ServerProcess]:
        """当前运行中的 Server 进程映射。"""
        return dict(self._processes)

    # ── 启动 ──

    async def start_all(self, specs: list[MCPServerSpec]) -> None:
        """启动所有 enabled 的 MCP Server 进程。

        Args:
            specs: MCP Server 规范列表。
        """
        for spec in specs:
            if not spec.enabled:
                logger.debug("跳过禁用的 Server: %s (%s)", spec.name, spec.key)
                continue
            if spec.key in self._processes:
                logger.warning("Server 已在运行: %s", spec.key)
                continue
            await self.start_one(spec)

    async def start_one(self, spec: MCPServerSpec) -> asyncio.subprocess.Process:
        """启动单个 MCP Server（stdio transport），返回子进程句柄。

        Args:
            spec: MCP Server 规范。

        Returns:
            子进程句柄。

        Raises:
            RuntimeError: 启动失败时。
        """
        logger.info("启动 MCP Server: %s (%s)", spec.name, spec.key)

        if not spec.command:
            raise RuntimeError(_Msg.NO_COMMAND.format(key=spec.key))

        temp_dir = _ensure_tempdir()

        try:
            process = await asyncio.create_subprocess_exec(
                *spec.command,
                *spec.args,
                cwd=str(spec.directory) if spec.directory else None,
                env=_subprocess_environment(spec.env, temp_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STDOUT_LIMIT,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(_Msg.START_FAILED_IO.format(key=spec.key, command=spec.command, error=exc)) from exc
        except OSError as exc:
            raise RuntimeError(_Msg.START_FAILED_OS.format(key=spec.key, error=exc)) from exc

        server_proc = ServerProcess(spec=spec, process=process)
        self._processes[spec.key] = server_proc
        server_proc.stderr_task = asyncio.create_task(
            self._forward_stderr(spec.key, process),
            name=f"mcp-stderr-{spec.key}",
        )

        # 启动健康检查任务
        server_proc.health_task = asyncio.create_task(self._health_check_loop(spec.key, server_proc))

        logger.info(
            "MCP Server %s 已启动 (PID: %s)",
            spec.key,
            process.pid,
        )
        return process

    # ── 停止 ──

    async def stop_all(self) -> None:
        """按逆序停止所有 MCP Server。"""
        keys = list(self._processes.keys())
        for key in reversed(keys):
            await self.stop_one(key)

    async def stop_one(self, key: str) -> None:
        """优雅停止单个 Server（发送 SIGTERM，超时后强制终止）。

        Args:
            key: Server 的 key。
        """
        server_proc = self._processes.get(key)
        if server_proc is None:
            logger.debug("Server %s 已不存在，跳过停止", key)
            return

        spec = server_proc.spec
        process = server_proc.process

        logger.info("停止 MCP Server: %s (%s)", spec.name, key)

        # 取消健康检查任务
        if server_proc.health_task is not None:
            server_proc.health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await server_proc.health_task

        # 优雅停止
        if process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await process.stdin.wait_closed()

            if hasattr(signal, "SIGTERM"):
                with contextlib.suppress(ProcessLookupError):
                    process.send_signal(signal.SIGTERM)  # type: ignore[arg-type]

            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                logger.warning("Server %s 超时未退出，强制终止", key)
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()

        if server_proc.stderr_task is not None:
            await server_proc.stderr_task

        del self._processes[key]
        logger.info("MCP Server %s 已停止", key)

    # ── 健康检查 ──

    async def _forward_stderr(self, key: str, process: asyncio.subprocess.Process) -> None:
        """Drain child diagnostics to file and optionally to the managed terminal."""
        if process.stderr is None:
            return
        while chunk := await process.stderr.read(4096):
            for message in chunk.decode(errors="replace").splitlines():
                if message:
                    logger.info(
                        "MCP Server stderr key=%s | %s",
                        key,
                        message,
                        extra={"aurora_terminal": self._terminal_logs},
                    )

    async def _health_check_loop(self, key: str, server_proc: ServerProcess) -> None:
        """定期检查单个 Server 进程状态。

        Args:
            key: Server 的 key。
            server_proc: Server 进程信息。
        """
        timeout = server_proc.spec.health_timeout_seconds
        try:
            while True:
                await asyncio.sleep(timeout)
                proc = server_proc.process
                if proc.returncode is not None:
                    logger.error(
                        "MCP Server %s 异常退出 (code=%s)",
                        key,
                        proc.returncode,
                    )
                    break
        except asyncio.CancelledError:
            pass
