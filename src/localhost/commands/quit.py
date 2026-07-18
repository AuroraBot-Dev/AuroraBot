"""Implementation of the process-wide ``/quit`` runtime command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.localhost.command_types import CommandControl, CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/quit", "/exit", "/q")
USAGE = "/quit"
DESCRIPTION = "优雅停止 Aurora 进程"


def configure(_parser: argparse.ArgumentParser) -> None:
    return None


async def handle(_context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    return CommandResult(ok=True, text="Aurora 正在退出。", control=CommandControl.SHUTDOWN_PROCESS)
