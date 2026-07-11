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

from scripts.cli.utils import PROJECT_ROOT, run
from scripts.cli.utils import console as c

_RUN_SERVE = ["uv", "run", "python", "-m", "src.localhost.cli", "serve"]
_RUN_CONSOLE = ["uv", "run", "python", "-m", "src.localhost.cli", "console"]


def _kill_tree(proc: subprocess.Popen) -> None:
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
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)


def register(sub: Any) -> None:
    """注册 serve / console 子命令。"""
    sub.add_parser("serve", help="启动开发调试 HTTP API 服务器")
    sub.add_parser("console", help="启动分层交互式本地控制台")


def serve(_args: argparse.Namespace) -> int:
    """启动开发调试 HTTP API 服务器。"""
    return run(_RUN_SERVE)


def console(_args: argparse.Namespace) -> int:
    """启动分层交互式本地控制台。"""
    return run(_RUN_CONSOLE)


def default(_args: argparse.Namespace) -> int:
    """同时启动 serve (后台) 和 console (前台)；console 退出后自动关闭 serve。"""
    c.print("[bold]启动 serve (后台) + console (前台) ...[/bold]\n")

    if os.name == "nt":
        serve_proc = subprocess.Popen(
            _RUN_SERVE,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    else:
        serve_proc = subprocess.Popen(
            _RUN_SERVE,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    try:
        time.sleep(2)
        if serve_proc.poll() is not None:
            c.print("[bold red]serve 启动失败[/bold red]")
            return 1
        return run(_RUN_CONSOLE)
    finally:
        _kill_tree(serve_proc)
        serve_proc.wait()
