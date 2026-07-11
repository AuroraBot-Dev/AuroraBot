"""check 子命令：ruff + pyright + pytest。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse

from scripts.cli.utils import console, run

_LINT_CMDS = [
    ["uv", "run", "ruff", "check", "bot.py", "src/", "tests/", "scripts/"],
    ["uv", "run", "ruff", "format", "--check", "bot.py", "src/", "tests/", "scripts/"],
    ["uv", "run", "pyright", "bot.py", "src/", "scripts/"],
]

_TEST_CMDS = [
    ["uv", "run", "pytest", "-v", "--cov=src"],
]


def register(sub: Any) -> None:
    """注册 check 子命令（含 --lint / --test 参数）。"""
    parser = sub.add_parser("check", help="运行代码质量检查")
    parser.add_argument("--lint", action="store_true", help="仅运行 lint (ruff + pyright)")
    parser.add_argument("--test", action="store_true", help="仅运行 pytest")


def check(args: argparse.Namespace) -> int:
    """执行检查并返回退出码。"""
    run_lint = not args.test
    run_test = not args.lint

    failed = 0
    if run_lint:
        for cmd in _LINT_CMDS:
            if run(cmd) != 0:
                failed += 1
    if run_test:
        for cmd in _TEST_CMDS:
            if run(cmd) != 0:
                failed += 1

    if failed:
        console.print(f"\n[bold red]{failed} check(s) failed[/bold red]")
    else:
        console.print("\n[bold green]All checks passed[/bold green]")
    return 0 if failed == 0 else 1
