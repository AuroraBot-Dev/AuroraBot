"""Implementation of ``aurora donk``."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from aurora.process import console, run_process

if TYPE_CHECKING:
    import argparse

NAME = "donk"


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(NAME, help="自动版本管理")
    sub = parser.add_subparsers(dest="donk_command", required=True)
    sub.add_parser("show", help="显示当前版本号")
    sub.add_parser("major", help="升级主版本号")
    sub.add_parser("minor", help="升级次版本号")
    sub.add_parser("patch", help="升级修订版本号")
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    subcommand = arguments.donk_command
    exit_code = run_process(["uv", "run", "--no-sync", "donk", subcommand], arguments.root)
    if exit_code != 0:
        console.print(f"[bold red]donk {subcommand} 执行失败[/bold red]")
        return exit_code
    version = _read_version(arguments.root)
    if subcommand == "show":
        if version:
            console.print(f"[bold green]当前版本:[/bold green] [bold cyan]{version}[/bold cyan]")
    elif version:
        console.print(f"[bold green]版本已更新为:[/bold green] [bold cyan]{version}[/bold cyan]")
    return 0


def _read_version(root: Any) -> str | None:
    try:
        result = subprocess.run(
            ["uv", "run", "--no-sync", "donk", "show"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except OSError:
        return None
