"""Declarative registry for the layered localhost command shell."""

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
    """Return the command set exposed by the local developer shell."""
    from src.localhost.commands.core import agent_command, help_command, pump_command, status_command, task_command
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
        ConsoleCommand(("/pump", "/p"), "/pump [1-100]", "推进 Agent turns", pump_command),
        ConsoleCommand(("/task",), "/task <task_id>", "查询 Task 与监督树", task_command),
        ConsoleCommand(("/agent",), "/agent <agent_id>", "查询 Agent 与邮箱", agent_command),
        ConsoleCommand(("/quit", "/exit", "/q"), "/quit", "退出控制台", quit_command),
    )
