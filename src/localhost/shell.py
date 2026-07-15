"""Interactive console adapter for localhost business commands."""

from __future__ import annotations

import asyncio
import shlex
from typing import TYPE_CHECKING

from src.localhost.registry import ConsoleCommand, command_specs
from src.utils.log_utils import get_logger

logger = get_logger("aurora.localhost.console")

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
    output("AuroraBot local console; 输入 /help 查看命令。")
    commands = {name: command for command in command_specs() for name in command.names}
    stop = asyncio.Event()
    scheduler = asyncio.create_task(runtime.run_forever(stop), name="aurora-console-scheduler")
    display = asyncio.create_task(_display_messages(runtime, output), name="aurora-console-output")
    logger.info("developer console started commands=%d", len(commands))
    try:
        while True:
            try:
                raw = (await asyncio.to_thread(readline, "aurora> ")).strip()
            except (EOFError, KeyboardInterrupt):
                output("")
                return
            if not raw:
                continue
            command, arguments = _parse(raw, commands)
            if command is None:
                logger.debug("console input rejected reason=unknown_or_invalid_command")
                output("未知命令；输入 /help 查看命令。")
                continue
            logger.debug("console command selected command=%s arguments=%d", command.names[0], len(arguments))
            result = await command.handler(runtime, arguments)
            if result == "__QUIT__":
                return
            output(result)
    finally:
        stop.set()
        display.cancel()
        await asyncio.gather(display, return_exceptions=True)
        await asyncio.gather(scheduler, return_exceptions=True)
        await runtime.shutdown()
        logger.info("developer console stopped")


async def _display_messages(runtime: AuroraRuntime, output: Callable[[str], None]) -> None:
    while True:
        output(f"bot> {await runtime.next_console_message()}")


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
