"""AuroraBot 项目命令的统一注册与分派入口。"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, cast

from aurora.commands import COMMAND_REGISTRARS

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aurora", description="AuroraBot AgentTree experimental core")
    subparsers = parser.add_subparsers(dest="command")
    for register in COMMAND_REGISTRARS:
        register(subparsers)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    executor = getattr(arguments, "executor", None)
    if executor is None:
        parser.print_help()
        return 0
    return cast("Callable[[argparse.Namespace], int]", executor)(arguments)


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
