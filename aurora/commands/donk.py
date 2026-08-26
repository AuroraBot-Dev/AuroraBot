"""实现 ``aurora donk`` 版本管理命令"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora.utils.environment import get_project_version
from aurora.utils.process import run_process

if TYPE_CHECKING:
    import argparse

NAME = "donk"
_SUBCOMMANDS = {
    "show": "显示当前版本号",
    "major": "升级主版本号",
    "minor": "升级次版本号",
    "patch": "升级修订版本号",
}


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(NAME, help="管理项目版本号")
    commands = parser.add_subparsers(dest="donk_command", required=True)
    for name, help_text in _SUBCOMMANDS.items():
        commands.add_parser(name, help=help_text)
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    subcommand = str(arguments.donk_command)
    pyproject = (arguments.root / "pyproject.toml").resolve()
    command = ("uv", "run", "--no-sync", "donk", subcommand, str(pyproject))
    exit_code = run_process(command, arguments.root)
    if exit_code != 0:
        sys.stderr.write(f"donk {subcommand} 执行失败。\n")
        return exit_code
    version = get_project_version(arguments.root)
    if version is not None:
        label = "当前版本" if subcommand == "show" else "版本已更新为"
        sys.stdout.write(f"{label}：{version}\n")
    return 0
