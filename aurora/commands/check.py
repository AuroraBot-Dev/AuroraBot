"""实现 ``aurora check``。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

NAME = "check"
_COMMANDS = (
    ("uv", "run", "--no-sync", "ruff", "check", "aurora", "src", "tests"),
    ("uv", "run", "--no-sync", "ruff", "format", "--check", "aurora", "src", "tests"),
    ("uv", "run", "--no-sync", "pyright", "aurora", "src", "tests"),
    ("uv", "run", "--no-sync", "pytest", "-q", "--cov=src", "--cov=aurora"),
)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(NAME, help="run lint, format, type and behavior checks")
    parser.set_defaults(executor=execute)


def execute(_arguments: argparse.Namespace) -> int:
    root = Path(__file__).parents[2]
    for command in _COMMANDS:
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0
