"""Implementation of the headless ``aurora run`` command."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aurora.runtime import RUN, run_runtime

if TYPE_CHECKING:
    import argparse

NAME = "run"


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(NAME, help="仅启动完整 Bot 后台循环")
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    asyncio.run(run_runtime(arguments.root, arguments.profile, RUN))
    return 0
