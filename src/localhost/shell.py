"""Interactive console adapter modeled after the former layered localhost shell."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from src.localhost.registry import ConsoleCommand, command_specs

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.localhost.runtime import AuroraRuntime


async def run_console(
    runtime: AuroraRuntime,
    *,
    readline: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> None:
    """Run the developer console; bare text is equivalent to ``/say <text>``."""
    output("AuroraBot vNext local console; 输入 /help 查看命令。")
    commands = {name: command for command in command_specs() for name in command.names}
    while True:
        try:
            raw = readline("aurora> ").strip()
        except (EOFError, KeyboardInterrupt):
            output("")
            return
        if not raw:
            continue
        command, arguments = _parse(raw, commands)
        if command is None:
            output("未知命令；输入 /help 查看命令。")
            continue
        result = await command.handler(runtime, arguments)
        if result == "__QUIT__":
            return
        output(result)
        for message in runtime.drain_console_messages():
            output(f"bot> {message}")


def _parse(raw: str, commands: dict[str, ConsoleCommand]) -> tuple[ConsoleCommand | None, tuple[str, ...]]:
    try:
        tokens = tuple(shlex.split(raw))
    except ValueError:
        return None, ()
    if not tokens:
        return None, ()
    if not tokens[0].startswith("/"):
        command = commands["/say"]
        return command, tokens
    return commands.get(tokens[0]), tokens[1:]
