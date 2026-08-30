"""实现 ``aurora donk`` 版本管理命令。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora.utils.process import EXIT_FAILURE, run_process
from aurora.utils.project import get_project_version

if TYPE_CHECKING:
    import argparse

    from aurora.commander import CommandSpec

COMMAND: CommandSpec = {
    "name": "donk",
    "help": "管理项目版本号",
    "subcommands": {
        "show": {"help": "显示当前版本号"},
        "major": {"help": "升级主版本号"},
        "minor": {"help": "升级次版本号"},
        "patch": {"help": "升级修订版本号"},
    },
}


def execute(arguments: argparse.Namespace) -> int:
    subcommand = str(arguments.subcommand)
    pyproject = arguments.root / "pyproject.toml"
    command = ("uv", "run", "--no-sync", "donk", subcommand, str(pyproject))
    exit_code = run_process(command, arguments.root)
    if exit_code != 0:
        sys.stderr.write(f"donk {subcommand} 执行失败。\n")
        return exit_code
    version = get_project_version(arguments.root)
    if version is not None:
        match subcommand:
            case "show":
                sys.stdout.write(f"当前版本：{version}\n")
            case "major" | "minor" | "patch":
                sys.stdout.write(f"版本已更新为：{version}\n")
            case _:
                sys.stderr.write(f"未知子命令：{subcommand}\n")
                return EXIT_FAILURE
    return 0
