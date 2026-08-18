"""实现 ``aurora check``"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora.utils.process import run_process

if TYPE_CHECKING:
    import argparse

NAME = "check"
_PATHS = ("aurora", "src", "tests")


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(NAME, help="运行代码质量检查")
    parser.add_argument("--lint", action="store_true", help="运行 Ruff 与 Pyright")
    parser.add_argument("--test", action="store_true", help="运行 Pytest 与覆盖率检查")
    parser.add_argument("--fix", action="store_true", help="允许 Ruff 修复和格式化代码")
    parser.add_argument("--unsafe-fixes", action="store_true", help="允许 Ruff 使用不安全修复")
    parser.add_argument("--check", action="store_true", help="修复代码时仍只预览格式变更")
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    """按选项运行 lint、类型、格式和测试检查，并汇总全部失败。"""
    run_lint = arguments.lint or not arguments.test
    run_test = arguments.test or not arguments.lint
    commands: list[tuple[str, ...]] = []
    if run_lint:
        check_flags = ("--fix",) if arguments.fix else ()
        if arguments.unsafe_fixes:
            check_flags = (*check_flags, "--unsafe-fixes")
        format_flags = () if arguments.fix and not arguments.check else ("--check",)
        commands.extend(
            (
                ("uv", "run", "--no-sync", "ruff", "check", *check_flags, *_PATHS),
                ("uv", "run", "--no-sync", "ruff", "format", *format_flags, *_PATHS),
                ("uv", "run", "--no-sync", "pyright", *_PATHS),
            )
        )
    if run_test:
        commands.append(("uv", "run", "--no-sync", "pytest", "-q", "--cov=src", "--cov=aurora"))
    failures = sum(run_process(command, arguments.root) != 0 for command in commands)
    if failures:
        sys.stderr.write(f"\n{failures} 项检查失败。\n")
        return 1
    sys.stdout.write("\n全部检查通过。\n")
    return 0
