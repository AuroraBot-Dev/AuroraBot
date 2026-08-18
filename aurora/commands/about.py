"""实现 ``aurora about``。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

NAME = "about"


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(NAME, help="说明当前实验核心")
    parser.set_defaults(executor=execute)


def execute(_arguments: argparse.Namespace) -> int:
    sys.stdout.write("AuroraBot 当前正在探索 AgentTree 与四角色对话的最小循环。\n")
    return 0
