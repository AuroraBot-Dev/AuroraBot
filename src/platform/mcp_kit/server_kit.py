"""MCP Server 进程生命周期管理器。

负责本地 stdio MCP Server 的启动、停止、重启和健康检查。
工具能力由 MCP Client 通过 tools/list 动态发现。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.platform.mcp_kit.server_spec import MCPServerSpec

logger = get_logger("MCPServerKit")


@dataclass(slots=True)
class ServerProcess:
    """运行的 MCP Server 进程信息。"""

    spec: MCPServerSpec
    process: asyncio.subprocess.Process
    health_task: asyncio.Task[None] | None = None


class MCPServerKit:
    """MCP Server 进程生命周期管理器。

    Usage::

        kit = MCPServerKit()
        await kit.start_all(specs)
        ...
        await kit.stop_all()
    """

    def __init__(self) -> None:
        self._processes: dict[str, ServerProcess] = {}

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
            msg = f"Server {spec.key} 没有配置启动命令"
            raise RuntimeError(msg)

        try:
            process = await asyncio.create_subprocess_exec(
                *spec.command,
                *spec.args,
                cwd=str(spec.directory) if spec.directory else None,
                env={**os.environ, **spec.env},
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=None,
            )
        except FileNotFoundError as exc:
            msg = f"启动 Server {spec.key} 失败: 命令未找到 {spec.command}"
            raise RuntimeError(msg) from exc
        except OSError as exc:
            msg = f"启动 Server {spec.key} 失败: {exc}"
            raise RuntimeError(msg) from exc

        server_proc = ServerProcess(spec=spec, process=process)
        self._processes[spec.key] = server_proc

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

        del self._processes[key]
        logger.info("MCP Server %s 已停止", key)

    async def restart_one(self, key: str) -> asyncio.subprocess.Process:
        """重启单个 Server。

        Args:
            key: Server 的 key。

        Returns:
            新的子进程句柄。
        """
        server_proc = self._processes.get(key)
        if server_proc is None:
            msg = f"Server {key} 不在运行中，无法重启"
            raise RuntimeError(msg)

        spec = server_proc.spec
        await self.stop_one(key)
        return await self.start_one(spec)

    # ── 健康检查 ──

    def health_report(self) -> dict[str, str]:
        """返回所有 Server 的健康状态。

        Returns:
            ``{key: "running" | "stopped" | "crashed"}`` 的映射。
        """
        report: dict[str, str] = {}
        for key, server_proc in self._processes.items():
            proc = server_proc.process
            if proc.returncode is None:
                report[key] = "running"
            elif proc.returncode == 0:
                report[key] = "stopped"
            else:
                report[key] = f"crashed (code={proc.returncode})"
        return report

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
