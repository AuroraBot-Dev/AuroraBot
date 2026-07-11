"""check 子命令：ruff + pyright + pytest。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse

from scripts.cli.utils import console, run

_FIXED_PATHS = ["bot.py", "src/", "tests/", "scripts/"]

_LINT_CMDS = [
    lambda args: ["uv", "run", "ruff", "check", *args_check_flags(args), *_FIXED_PATHS],
    lambda _args: ["uv", "run", "ruff", "format", "--check", *_FIXED_PATHS],
    lambda _args: ["uv", "run", "pyright", "bot.py", "src/", "scripts/"],
]

_TEST_CMDS = [
    lambda _args: ["uv", "run", "pytest", "-v", "--cov=src"],
]


def args_check_flags(args: argparse.Namespace) -> list[str]:
    """根据 --fix / --unsafe-fixes 返回 ruff check 的透传参数。"""
    flags: list[str] = []
    if args.fix:
        flags.append("--fix")
    if args.unsafe_fixes:
        flags.append("--unsafe-fixes")
    return flags


def register(sub: Any) -> None:
    """注册 check 子命令（含 --lint / --test 参数）。"""
    parser = sub.add_parser("check", help="运行代码质量检查")
    parser.add_argument("--lint", action="store_true", help="仅运行 lint (ruff + pyright)")
    parser.add_argument("--test", action="store_true", help="仅运行 pytest")
    parser.add_argument("--fix", action="store_true", help="透传 ruff check --fix")
    parser.add_argument("--unsafe-fixes", action="store_true", help="透传 ruff check --unsafe-fixes")


def check(args: argparse.Namespace) -> int:
    """执行检查并返回退出码。"""
    run_lint = args.lint or not args.test
    run_test = args.test or not args.lint

    failed = 0
    if run_lint:
        for build in _LINT_CMDS:
            if run(build(args)) != 0:
                failed += 1
    if run_test:
        for build in _TEST_CMDS:
            if run(build(args)) != 0:
                failed += 1

    if failed:
        console.print(f"\n[bold red]{failed} check(s) failed[/bold red]")
    else:
        console.print("\n[bold green]All checks passed[/bold green]")
    return 0 if failed == 0 else 1
