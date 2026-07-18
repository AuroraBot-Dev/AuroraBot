"""Implementation of ``aurora dev`` and the no-argument default."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aurora.runtime import DEV, run_runtime

if TYPE_CHECKING:
    import argparse

NAME = "dev"


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(NAME, help="启动 Runtime、Dashboard 和 Console")
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    asyncio.run(run_runtime(arguments.root, arguments.profile, DEV))
    return 0
