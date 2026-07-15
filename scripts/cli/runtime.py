"""serve / console / default 子命令。"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Generator
    from typing import Any

from scripts.cli.utils import console as c
from scripts.cli.utils import run

_RUN_SERVE = ["uv", "run", "python", "-m", "src.localhost.cli", "serve"]
_RUN_CONSOLE = ["uv", "run", "python", "-m", "src.localhost.cli", "console"]
_RUN_COMBINED = ["uv", "run", "python", "-m", "src.localhost.cli"]


# RFC 0007 compatibility helpers. The default command no longer uses a second process.
def _popen_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _kill_tree(proc: subprocess.Popen, *, force: bool = False) -> None:
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
    """在一个进程内启动共享 Runtime 的 serve 与 console。"""
    c.print("[bold]启动单 Runtime serve + console ...[/bold]\n")
    return run(_RUN_COMBINED)
