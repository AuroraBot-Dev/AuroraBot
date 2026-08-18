"""AuroraBot 项目命令行入口。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_CHECK_COMMANDS = (
    ("uv", "run", "--no-sync", "ruff", "check", "aurora", "src", "tests"),
    ("uv", "run", "--no-sync", "ruff", "format", "--check", "aurora", "src", "tests"),
    ("uv", "run", "--no-sync", "pyright", "aurora", "src", "tests"),
    ("uv", "run", "--no-sync", "pytest", "-q", "--cov=src", "--cov=aurora"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aurora", description="AuroraBot AgentTree experimental core")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("check", help="run lint, format, type and behavior checks")
    subparsers.add_parser("about", help="describe the current experimental core")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
    if arguments.command == "about":
        sys.stdout.write("AuroraBot currently explores one AgentTree + four-role chat loop.\n")
        return 0
    root = Path(__file__).parents[1]
    for command in _CHECK_COMMANDS:
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
