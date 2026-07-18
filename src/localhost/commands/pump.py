"""Implementation of the ``/pump`` runtime command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.localhost.command_types import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/pump", "/p")
USAGE = "/pump [1-100]"
DESCRIPTION = "推进 Agent turns"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("turns", nargs="?", default=1, type=int, choices=range(1, 101))


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    data = await context.runtime.pump(arguments.turns)
    return CommandResult(ok=True, text=json.dumps(data, ensure_ascii=False), data=data)
