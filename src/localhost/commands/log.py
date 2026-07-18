"""Implementation of the ``/log`` terminal logging command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.localhost.command_types import CommandResult
from src.utils.log_utils import configure_console_logging, console_logging_status

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/log",)
USAGE = "/log [on|off] [--level <debug|info|warning|error|critical>]"
DESCRIPTION = "控制当前进程的终端日志"
LEVELS = ("debug", "info", "warning", "warn", "error", "critical")


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("state", nargs="?", choices=("on", "off"))
    parser.add_argument("--level", type=str.lower, choices=LEVELS)


async def handle(_context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    if arguments.state is not None or arguments.level is not None:
        level = "WARNING" if arguments.level == "warn" else arguments.level
        configure_console_logging(
            enabled=None if arguments.state is None else arguments.state == "on",
            level=level,
        )
    status = console_logging_status()
    return CommandResult(ok=True, text=json.dumps(status, ensure_ascii=False), data=status)
