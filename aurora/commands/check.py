"""实现 ``aurora check``。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora.utils.process import EXIT_FAILURE, run_process

if TYPE_CHECKING:
    import argparse

    from aurora.commander import CommandSpec

COMMAND: CommandSpec = {
    "name": "check",
    "help": "运行代码质量检查",
    "options": {
        "--lint": "运行 Ruff 与 Pyright",
        "--test": "运行 Pytest 与覆盖率检查",
        "--fix": "允许 Ruff 修复和格式化代码",
        "--unsafe-fixes": "允许 Ruff 使用不安全修复",
        "--check": "修复代码时仍只预览格式变更",
    },
}
_RUN = ("uv", "run", "--no-sync")
_PATHS = ("aurora", "ops", "src", "tests")
_TEST_COMMAND = (*_RUN, "pytest", "-q", *(f"--cov={path}" for path in _PATHS if path != "tests"))


def _lint_commands(arguments: argparse.Namespace) -> tuple[tuple[str, ...], ...]:
    """按选项构造 Ruff 检查、Ruff 格式与 Pyright 三条命令。"""
    check_flags = tuple(
        flag
        for flag, enabled in (
            ("--fix", arguments.fix),
            ("--unsafe-fixes", arguments.unsafe_fixes),
        )
        if enabled
    )
    format_flags = () if arguments.fix and not arguments.check else ("--check",)
    return (
        (*_RUN, "ruff", "check", *check_flags, *_PATHS),
        (*_RUN, "ruff", "format", *format_flags, *_PATHS),
        (*_RUN, "pyright", *_PATHS),
    )


def execute(arguments: argparse.Namespace) -> int:
    """按选项运行 lint、类型、格式和测试检查，并汇总全部失败。"""
    if arguments.lint and not arguments.test:
        commands = _lint_commands(arguments)
    elif arguments.test and not arguments.lint:
        commands = (_TEST_COMMAND,)
    else:
        commands = (*_lint_commands(arguments), _TEST_COMMAND)
    failures = sum(run_process(command, arguments.root) != 0 for command in commands)
    if failures:
        sys.stderr.write(f"\n{failures} 项检查失败。\n")
        return EXIT_FAILURE
    sys.stdout.write("\n全部检查通过。\n")
    return 0
