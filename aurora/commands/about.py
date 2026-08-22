"""实现 ``aurora about``"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora.utils.assets import ABOUT, LOGO

if TYPE_CHECKING:
    import argparse

NAME = "about"


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(NAME, help="了解 AuroraBot")
    parser.set_defaults(executor=execute)


def execute(_arguments: argparse.Namespace) -> int:
    sys.stdout.write(LOGO + "\n" + ABOUT)
    return 0
