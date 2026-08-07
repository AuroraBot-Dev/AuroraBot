"""传输无关运行时命令的声明式目录。"""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.contracts import (
    CommandContext,
    CommandResult,
)

CommandHandler = Callable[[CommandContext, argparse.Namespace], Awaitable[CommandResult]]
CommandConfigurator = Callable[[argparse.ArgumentParser], None]


@dataclass(frozen=True, slots=True)
class ConsoleCommand:
    """控制台命令的声明式描述：名称、用法、参数配置与异步处理器。"""

    names: tuple[str, ...]
    usage: str
    description: str
    configure: CommandConfigurator
    handler: CommandHandler


def command_specs() -> tuple[ConsoleCommand, ...]:
    """返回 Console 与 Dashboard 输入共用的命令集。"""
    from ops.commands import (
        agent,
        clear,
        event,
        log,
        pump,
        say,
        status,
        task,
    )
    from ops.commands import (
        help as help_command,
    )
    from ops.commands import (
        quit as quit_command,
    )

    return (
        ConsoleCommand(
            help_command.NAMES,
            help_command.USAGE,
            help_command.DESCRIPTION,
            help_command.configure,
            help_command.handle,
        ),
        ConsoleCommand(status.NAMES, status.USAGE, status.DESCRIPTION, status.configure, status.handle),
        ConsoleCommand(say.NAMES, say.USAGE, say.DESCRIPTION, say.configure, say.handle),
        ConsoleCommand(event.NAMES, event.USAGE, event.DESCRIPTION, event.configure, event.handle),
        ConsoleCommand(pump.NAMES, pump.USAGE, pump.DESCRIPTION, pump.configure, pump.handle),
        ConsoleCommand(task.NAMES, task.USAGE, task.DESCRIPTION, task.configure, task.handle),
        ConsoleCommand(agent.NAMES, agent.USAGE, agent.DESCRIPTION, agent.configure, agent.handle),
        ConsoleCommand(log.NAMES, log.USAGE, log.DESCRIPTION, log.configure, log.handle),
        ConsoleCommand(clear.NAMES, clear.USAGE, clear.DESCRIPTION, clear.configure, clear.handle),
        ConsoleCommand(
            quit_command.NAMES,
            quit_command.USAGE,
            quit_command.DESCRIPTION,
            quit_command.configure,
            quit_command.handle,
        ),
    )
