"""Implementation of the Console ``/clear`` runtime command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.localhost.command_types import CommandControl, CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/clear", "/cls")
USAGE = "/clear"
DESCRIPTION = "清空 Console（别名 /cls）"


def configure(_parser: argparse.ArgumentParser) -> None:
    return None


async def handle(_context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    return CommandResult(ok=True, publish_reply=False, control=CommandControl.CLEAR_CONSOLE)
