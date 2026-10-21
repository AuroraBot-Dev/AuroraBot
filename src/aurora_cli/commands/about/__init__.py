"""提供 ``aurora about`` 命令插件。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora_cli.plugins import command_plugin
from aurora_cli.utils.platform import detect_os
from aurora_cli.utils.project import get_git_revision, get_project_version
from aurora_cli.utils.table import render_table

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora_cli.contracts.command import CommandSpec

COMMAND: CommandSpec = {
    "name": "about",
    "help": "了解 AuroraBot",
}

LOGO = """\
                              ▄          ▄
▄▀▀█ █  █ █▀▀▀ █▀▀█ █▀▀▀ ▄▀▀█ █▀▀█ █▀▀█ ▀█▀▀
█░░█ █░░█ █    █░░█ █    █░░█ █░░█ █░░█  █░░
▀▀▀▀ ▀▀▀▀ ▀    ▀▀▀▀ ▀    ▀▀▀▀ ▀▀▀▀ ▀▀▀▀  ▀▀▀
"""

ABOUT = """\
你说得对, 但是 AuroraBot 是新一代内驱式, 自主决策的 Bot 框架,
它为 Agent 提供可以"生活"的运行环境. 她有自己的人格、状态, 可
以在需要时与人和外部世界建立联系.  在她的世界里, 所有的消息都
有一个"媒介": 你发给她的消息也必须先成为一个应用通知喔~
"""

LINKS: tuple[tuple[str, str], ...] = (
    ("文档站", "https://www.aurorabot.org/"),
    ("项目地址", "https://www.github.com/AuroraBot-Dev/AuroraBot"),
    ("爱发电", "https://ifdian.net/a/aurorabot"),
)


def _info_rows(root: Path) -> list[tuple[str, str]]:
    rows = [("系统", detect_os())]
    version = get_project_version(root)
    if version is not None:
        rows.append(("版本", version))
    revision = get_git_revision(root)
    if revision is not None:
        rows.append(("提交", revision))
    return rows


def execute(arguments: argparse.Namespace) -> int:
    table = render_table(
        ("项目", "内容"),
        [*_info_rows(arguments.root), *LINKS],
    )
    sys.stdout.write(f"{LOGO}\n{ABOUT}\n{table}\n")
    return 0


MODULE = command_plugin("aurora.cli.commands.about", COMMAND, execute)
