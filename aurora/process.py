"""供进程级命令共享的轻量子进程辅助工具。"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

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
