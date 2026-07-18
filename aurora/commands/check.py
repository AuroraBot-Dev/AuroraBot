"""Implementation of ``aurora check``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.process import console, run_process

if TYPE_CHECKING:
    import argparse

NAME = "check"
_PATHS = ["aurora/", "src/", "tests/"]


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(NAME, help="运行代码质量检查")
    parser.add_argument("--lint", action="store_true", help="仅运行 Ruff 与 Pyright")
    parser.add_argument("--test", action="store_true", help="仅运行 pytest")
    parser.add_argument("--fix", action="store_true", help="透传 Ruff --fix")
    parser.add_argument("--unsafe-fixes", action="store_true", help="透传 Ruff --unsafe-fixes")
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    run_lint = arguments.lint or not arguments.test
    run_test = arguments.test or not arguments.lint
    commands: list[list[str]] = []
    if run_lint:
        flags = []
        if arguments.fix:
            flags.append("--fix")
        if arguments.unsafe_fixes:
            flags.append("--unsafe-fixes")
        commands.extend(
            (
                ["uv", "run", "ruff", "check", *flags, *_PATHS],
                ["uv", "run", "ruff", "format", "--check", *_PATHS],
                ["uv", "run", "pyright", "aurora/", "src/"],
            )
        )
    if run_test:
        commands.append(["uv", "run", "pytest", "-v", "--cov=src", "--cov=aurora"])
    failures = sum(run_process(command, arguments.root) != 0 for command in commands)
    if failures:
        console.print(f"\n[bold red]{failures} check(s) failed[/bold red]")
    else:
        console.print("\n[bold green]All checks passed[/bold green]")
    return 1 if failures else 0
