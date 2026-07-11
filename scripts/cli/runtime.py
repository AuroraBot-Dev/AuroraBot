"""serve / console / default 子命令。"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse
    from collections.abc import Generator

from scripts.cli.utils import PROJECT_ROOT, run
from scripts.cli.utils import console as c

_RUN_SERVE = ["uv", "run", "python", "-m", "src.localhost.cli", "serve"]
_RUN_CONSOLE = ["uv", "run", "python", "-m", "src.localhost.cli", "console"]


# ── 进程树管理 ──────────────────────────────────────────────────────────────


def _popen_kwargs() -> dict[str, Any]:
    """返回启动 serve 后台进程的跨平台参数。"""
    kwargs: dict[str, Any] = {"cwd": str(PROJECT_ROOT), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _kill_tree(proc: subprocess.Popen, *, force: bool = False) -> None:
    """Kill a process and all its descendants."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL if force else signal.SIGTERM)


@contextlib.contextmanager
def _background_server() -> Generator[subprocess.Popen]:
    """上下文管理器：启动 serve 后台进程，退出时自动杀进程树。"""
    proc = subprocess.Popen(_RUN_SERVE, **_popen_kwargs())
    try:
        yield proc
    finally:
        _kill_tree(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_tree(proc, force=True)
            proc.wait()


# ── 子命令注册 ──────────────────────────────────────────────────────────────


def register(sub: Any) -> None:
    """注册 serve / console 子命令。"""
    sub.add_parser("serve", help="启动开发调试 HTTP API 服务器")
    sub.add_parser("console", help="启动分层交互式本地控制台")


# ── 子命令处理 ──────────────────────────────────────────────────────────────


def serve(_args: argparse.Namespace) -> int:
    """启动开发调试 HTTP API 服务器。"""
    return run(_RUN_SERVE)


def console(_args: argparse.Namespace) -> int:
    """启动分层交互式本地控制台。"""
    return run(_RUN_CONSOLE)


def default(_args: argparse.Namespace) -> int:
    """同时启动 serve (后台) 和 console (前台)；console 退出后自动关闭 serve。"""
    c.print("[bold]启动 serve (后台) + console (前台) ...[/bold]\n")
    with _background_server() as serve_proc:
        time.sleep(2)
        if serve_proc.poll() is not None:
            c.print("[bold red]serve 启动失败[/bold red]")
            return 1
        return run(_RUN_CONSOLE)
