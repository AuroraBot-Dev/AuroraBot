"""Implementation of the ``/say`` conversation command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.localhost.command_types import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/say", "/s")
USAGE = "/say <message>"
DESCRIPTION = "投递 message.received AMP"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("message", nargs="+")


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    message = " ".join(arguments.message).strip()
    task_id = await context.runtime.submit_conversation(context.request.with_text(message), message)
    return CommandResult(ok=True, text=f"已投递消息 AMP: {task_id}", task_id=task_id, publish_reply=False)
