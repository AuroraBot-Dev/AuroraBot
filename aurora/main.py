"""Single argparse entry point for all Aurora process commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from aurora.commands import dev
from aurora.registry import register_commands

if TYPE_CHECKING:
    from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aurora", description="AuroraBot CLI")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="配置与数据根目录")
    parser.add_argument("--profile", help="config/profiles 下的配置 profile")
    register_commands(parser.add_subparsers(dest="command"))
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    executor = getattr(arguments, "executor", dev.execute)
    return executor(arguments)


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
