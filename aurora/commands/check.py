"""实现 ``aurora check`` 子命令。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.process import console, run_process

if TYPE_CHECKING:
    import argparse

NAME = "check"
_PATHS = ["aurora/", "src/", "tests/"]


def register(subparsers: Any) -> None:
    """向子解析器注册 check 命令及其 lint/test/fix 等选项。"""
    parser = subparsers.add_parser(NAME, help="代码质量检查")
    parser.add_argument("--lint", action="store_true", help="运行 ruff 与 pyright")
    parser.add_argument("--test", action="store_true", help="运行 pytest")
    parser.add_argument("--fix", action="store_true", help="允许 ruff check --fix")
    parser.add_argument("--unsafe-fixes", action="store_true", help="允许 ruff check --unsafe-fixes")
    parser.add_argument("--check", action="store_true", help="预览 ruff format")
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    """按用户选项依次运行 lint（ruff + pyright）和/或 pytest，汇总并展示结果。"""
    # 未指定时默认两者都运行
    run_lint = arguments.lint or not arguments.test
    run_test = arguments.test or not arguments.lint
    commands: list[list[str]] = []
    if run_lint:
        flags_check = []
        flags_format = []
        if arguments.fix:
            flags_check.append("--fix")
        if arguments.unsafe_fixes:
            flags_check.append("--unsafe-fixes")
        if arguments.check:
            flags_format.append("--check")
        commands.extend(
            (
                ["uv", "run", "--no-sync", "ruff", "check", *flags_check, *_PATHS],
                ["uv", "run", "--no-sync", "ruff", "format", *flags_format, *_PATHS],
                ["uv", "run", "--no-sync", "pyright", "aurora/", "src/"],
            )
        )
    if run_test:
        commands.append(["uv", "run", "--no-sync", "pytest", "-v", "--cov=src", "--cov=aurora"])
    # 依次执行并累计失败数
    failures = sum(run_process(command, arguments.root) != 0 for command in commands)
    if failures:
        console.print(f"\n[bold red]{failures} check(s) failed[/bold red]")
    else:
        console.print("\n[bold green]All checks passed![/bold green]")
    return 1 if failures else 0
