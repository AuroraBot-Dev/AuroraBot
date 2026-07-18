"""Implementation of the ``/help`` runtime command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.localhost.command_types import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/help", "/h")
USAGE = "/help"
DESCRIPTION = "显示可用命令"


def configure(_parser: argparse.ArgumentParser) -> None:
    return None


async def handle(_context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    from src.localhost.registry import command_specs

    text = "\n".join(f"{spec.usage:<58} {spec.description}" for spec in command_specs())
    return CommandResult(ok=True, text=text)
