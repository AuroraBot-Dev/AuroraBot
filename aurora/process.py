"""Small subprocess helpers shared by process-level commands."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from pathlib import Path

console = Console(highlight=False)


def run_process(command: list[str], root: Path) -> int:
    console.print(f"\n[bold cyan]>>> {' '.join(command)}[/bold cyan]")
    try:
        result = subprocess.run(command, cwd=root, check=False)
    except KeyboardInterrupt:
        return 130
    if result.returncode != 0:
        console.print(f"[bold red]FAILED (exit {result.returncode})[/bold red]")
    return result.returncode
