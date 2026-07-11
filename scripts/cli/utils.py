"""CLI 共享工具。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

console = Console(highlight=False)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def run(cmd: list[str]) -> int:
    """运行命令并返回退出码。"""
    console.print(f"\n[bold cyan]>>> {' '.join(cmd)}[/bold cyan]")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    if result.returncode != 0:
        console.print(f"[bold red]FAILED (exit {result.returncode})[/bold red]")
    return result.returncode
