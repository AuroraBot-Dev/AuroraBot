"""提供 ``aurora check`` 命令插件。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora_cli.plugins import command_plugin
from aurora_cli.utils.process import EXIT_FAILURE, run_process

if TYPE_CHECKING:
    import argparse

    from aurora_cli.contracts.command import CommandSpec

COMMAND: CommandSpec = {
    "name": "check",
    "help": "运行代码质量检查",
    "options": {
        "--lint": "运行 Ruff 与 Pyright",
        "--test": "运行 Pytest",
        "--coverage": "为测试生成覆盖率报告并检查最低覆盖率",
        "--fix": "允许 Ruff 修复和格式化代码",
        "--unsafe-fixes": "允许 Ruff 使用不安全修复",
        "--check": "修复代码时仍只预览格式变更",
    },
}
_RUN = ("uv", "run", "--no-sync")
_PATHS = ("src", "tests")


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
    test_command = (*_RUN, "pytest", "-q", *(("--cov",) if arguments.coverage else ()))
    if arguments.lint and not (arguments.test or arguments.coverage):
        commands = _lint_commands(arguments)
    elif arguments.test and not arguments.lint:
        commands = (test_command,)
    else:
        commands = (*_lint_commands(arguments), test_command)
    failures = sum(run_process(command, arguments.root) != 0 for command in commands)
    if failures:
        sys.stderr.write(f"\n{failures} 项检查失败。\n")
        return EXIT_FAILURE
    sys.stdout.write("\n全部检查通过。\n")
    return 0


MODULE = command_plugin("aurora.cli.commands.check", COMMAND, execute)
