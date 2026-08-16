"""供进程级命令共享的子进程与进程内 CLI 调用辅助工具。"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import click
from rich.console import Console

if TYPE_CHECKING:
    from pathlib import Path

console = Console(highlight=False)


def run_process(command: list[str], root: Path) -> int:
    """在指定根目录下运行一个子进程命令，并输出格式化结果。

    返回子进程的退出码。捕获 KeyboardInterrupt 时返回 130。
    """
    console.print(f"\n[bold cyan]>>> {' '.join(command)}[/bold cyan]")
    try:
        result = subprocess.run(command, cwd=root, check=False)
    except KeyboardInterrupt:
        return 130
    if result.returncode != 0:
        console.print(f"[bold red]FAILED (exit {result.returncode})[/bold red]")
    return result.returncode


def invoke_cli(cli: Any, args: list[str], prog_name: str) -> int:
    """在进程内调用一个 click CLI，避免子进程环境解析开销。

    捕获 ClickException 时输出错误并返回 1；CLI 返回 None 视为成功。
    """
    try:
        result = cli.main(args=args, prog_name=prog_name, standalone_mode=False)
    except click.ClickException as error:
        console.print(f"[bold red]{error}[/bold red]")
        return 1
    return 0 if result is None else int(result)
