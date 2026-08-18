"""实现 ``aurora about``。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

NAME = "about"


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(NAME, help="describe the current experimental core")
    parser.set_defaults(executor=execute)


def execute(_arguments: argparse.Namespace) -> int:
    sys.stdout.write("AuroraBot currently explores one AgentTree + four-role chat loop.\n")
    return 0
