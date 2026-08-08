"""``/say`` 对话命令的实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import CommandResult
from src.utils import console_logging_status

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/say", "/s")
USAGE = "/say <message>"
DESCRIPTION = "投递 message.received AMP"


def configure(parser: argparse.ArgumentParser) -> None:
    """配置 /say 命令参数：多词拼接的消息体。"""
    parser.add_argument("message", nargs="+")


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    """将用户消息拼装为对话 AMP 并提交到运行时。"""
    message = " ".join(arguments.message).strip()
    message_id = await context.runtime.submit_conversation(context.request.with_text(message), message)
    ack = f"已投递消息 AMP: {message_id}" if console_logging_status()["enabled"] else None
    return CommandResult(ok=True, text=ack, message_id=message_id, publish_reply=False)
