"""AuroraBot CLI — `uv run aurora <subcommand>`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from rich.console import Console

console = Console(highlight=False)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str]) -> int:
    """Run a command and return its exit code."""
    console.print(f"\n[bold cyan]>>> {' '.join(cmd)}[/bold cyan]")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    if result.returncode != 0:
        console.print(f"[bold red]FAILED (exit {result.returncode})[/bold red]")
    return result.returncode


def cmd_check(_args: argparse.Namespace) -> int:
    """Run all code quality checks: ruff, format, pyright, pytest."""
    failed = 0
    for cmd in [
        ["uv", "run", "ruff", "check", "bot.py", "src/", "tests/"],
        ["uv", "run", "ruff", "format", "--check", "bot.py", "src/", "tests/"],
        ["uv", "run", "pyright", "bot.py", "src/"],
        ["uv", "run", "pytest", "--cov=src"],
    ]:
        rc = _run(cmd)
        if rc != 0:
            failed += 1
    if failed:
        console.print(f"\n[bold red]{failed} check(s) failed[/bold red]")
    else:
        console.print("\n[bold green]All checks passed[/bold green]")
    return 0 if failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="aurora", description="AuroraBot CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="运行所有代码质量检查")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "check":
        sys.exit(cmd_check(args))


if __name__ == "__main__":
    main()
