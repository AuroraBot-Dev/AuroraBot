"""Single parser and router for all slash-prefixed runtime commands."""

from __future__ import annotations

import argparse
import shlex
from typing import TYPE_CHECKING, NoReturn

from src.localhost.command_types import CommandContext, CommandResult, RuntimeInput
from src.localhost.registry import ConsoleCommand, command_specs

if TYPE_CHECKING:
    from src.localhost.command_types import RuntimeCommandPort


class CommandParseError(ValueError):
    """Raised instead of allowing argparse to terminate the process."""


class _CommandParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CommandParseError(message)


class CommandRouter:
    def __init__(self, runtime: RuntimeCommandPort) -> None:
        self._runtime = runtime
        self._commands = {name: command for command in command_specs() for name in command.names}

    async def route(self, request: RuntimeInput) -> CommandResult:
        raw = request.text.strip()
        if not raw:
            return CommandResult(ok=False, text="消息不能为空")
        if not raw.startswith("/"):
            return await self._conversation(request, raw)
        return await self._command(request, raw)

    async def _command(self, request: RuntimeInput, raw: str) -> CommandResult:
        try:
            tokens = tuple(shlex.split(raw))
        except ValueError as error:
            return CommandResult(ok=False, text=f"命令解析失败: {error}")
        if not tokens:
            return CommandResult(ok=False, text="消息不能为空")
        command = self._commands.get(tokens[0].lower())
        if command is None:
            return CommandResult(ok=False, text="未知命令；输入 /help 查看命令。")
        try:
            arguments = self._parse(command, tokens[1:])
        except CommandParseError as error:
            return CommandResult(ok=False, text=f"参数错误: {error}\n用法: {command.usage}")
        return await command.handler(CommandContext(self._runtime, request), arguments)

    async def _conversation(self, request: RuntimeInput, text: str) -> CommandResult:
        message_id = await self._runtime.submit_conversation(request, text)
        return CommandResult(
            ok=True,
            text=f"已投递消息 AMP: {message_id}",
            message_id=message_id,
            publish_reply=False,
        )

    @staticmethod
    def _parse(command: ConsoleCommand, arguments: tuple[str, ...]) -> argparse.Namespace:
        parser = _CommandParser(add_help=False, prog=command.names[0])
        command.configure(parser)
        return parser.parse_args(arguments)


def is_conversation_input(value: str) -> bool:
    raw = value.strip()
    if not raw:
        return False
    if not raw.startswith("/"):
        return True
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return False
    return len(tokens) > 1 and tokens[0].lower() in {"/say", "/s"}
