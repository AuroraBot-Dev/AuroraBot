"""所有斜杠前缀运行时命令的单一解析器与路由器。"""

from __future__ import annotations

import argparse
import shlex
from typing import TYPE_CHECKING, NoReturn

from src.localhost.command_types import CommandContext, CommandResult, RuntimeInput
from src.localhost.registry import ConsoleCommand, command_specs

if TYPE_CHECKING:
    from src.localhost.command_types import RuntimeCommandPort


class CommandParseError(ValueError):
    """替代 argparse 终止进程而抛出的解析异常。"""


class _CommandParser(argparse.ArgumentParser):
    """自定义 argparse 解析器，将错误重定向为 CommandParseError 而非退出进程。"""

    def error(self, message: str) -> NoReturn:
        raise CommandParseError(message)


class CommandRouter:
    """命令路由器：将输入文本按斜杠前缀判定为命令或对话并分发处理。"""

    def __init__(self, runtime: RuntimeCommandPort) -> None:
        self._runtime = runtime
        self._commands = {name: command for command in command_specs() for name in command.names}

    async def route(self, request: RuntimeInput) -> CommandResult:
        """路由入口：无斜杠前缀则走对话通道，否则解析为命令。"""
        raw = request.text.strip()
        if not raw.startswith("/"):
            return await self._conversation(request, raw)
        return await self._command(request, raw)

    async def _command(self, request: RuntimeInput, raw: str) -> CommandResult:
        """解析并执行斜杠命令，包含参数解析与错误处理。"""
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
        """将纯文本输入作为对话消息提交到运行时。"""
        message_id = await self._runtime.submit_conversation(request, text)
        return CommandResult(ok=True, text=None, message_id=message_id, publish_reply=False)

    @staticmethod
    def _parse(command: ConsoleCommand, arguments: tuple[str, ...]) -> argparse.Namespace:
        """构建命令专属解析器并解析参数。"""
        parser = _CommandParser(add_help=False, prog=command.names[0])
        command.configure(parser)
        return parser.parse_args(arguments)
