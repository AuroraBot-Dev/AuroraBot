"""实现 ``aurora about``。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora.utils.environment import get_git_revision, get_project_version
from aurora.utils.platform import detect_os

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora.commander import CommandSpec

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

文档站:     https://www.aurorabot.org/
项目地址:   https://www.github.com/AuroraBot-Dev/AuroraBot
爱发电:     https://ifdian.net/a/aurorabot
"""


def _info_line(root: Path) -> str:
    version = get_project_version(root)
    revision = get_git_revision(root)
    parts = [f"系统：{detect_os()}"]
    if version is not None:
        parts.append(f"版本：{version}")
    if revision is not None:
        parts.append(f"提交：{revision}")
    return " | ".join(parts)


def execute(arguments: argparse.Namespace) -> int:
    sys.stdout.write(LOGO + "\n" + _info_line(arguments.root) + "\n\n" + ABOUT + "\n")
    return 0
