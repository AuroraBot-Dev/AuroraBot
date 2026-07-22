"""Implementation of the ``/say`` conversation command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.localhost.command_types import CommandResult
from src.utils.log_utils import console_logging_status

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
    message_id = await context.runtime.submit_conversation(context.request.with_text(message), message)
    ack = f"已投递消息 AMP: {message_id}" if console_logging_status()["enabled"] else None
    return CommandResult(ok=True, text=ack, message_id=message_id, publish_reply=False)
