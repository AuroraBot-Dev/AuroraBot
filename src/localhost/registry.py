"""Declarative registry for the layered vNext localhost command shell."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.localhost.runtime import AuroraRuntime

CommandHandler = Callable[[AuroraRuntime, tuple[str, ...]], Awaitable[str]]


async def quit_command(_runtime: AuroraRuntime, _arguments: tuple[str, ...]) -> str:
    return "__QUIT__"


@dataclass(frozen=True, slots=True)
class ConsoleCommand:
    names: tuple[str, ...]
    usage: str
    description: str
    handler: CommandHandler


def command_specs() -> tuple[ConsoleCommand, ...]:
    """Return the command set without importing legacy localhost command modules."""
    from src.localhost.commands.core import cycle_command, help_command, record_command, status_command
    from src.localhost.commands.emit import event_command
    from src.localhost.commands.say import say_command

    return (
        ConsoleCommand(("/help", "/h"), "/help", "显示可用命令", help_command),
        ConsoleCommand(("/status",), "/status", "显示本地运行器状态", status_command),
        ConsoleCommand(("/say", "/s"), "/say <message>", "投递 message.received AMP", say_command),
        ConsoleCommand(
            ("/event", "/e"),
            "/event <type> [--source APP] [--session ID] [--summary TEXT] [--data JSON]",
            "投递任意 AMP 事件",
            event_command,
        ),
        ConsoleCommand(("/cycle", "/c"), "/cycle [1-100]", "推进 Kernel 周期", cycle_command),
        ConsoleCommand(("/record",), "/record <record_id>", "查询审计记录", record_command),
        ConsoleCommand(("/quit", "/exit", "/q"), "/quit", "退出控制台", quit_command),
    )
