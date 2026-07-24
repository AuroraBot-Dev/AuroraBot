"""``/help`` 运行时命令的实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.event import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/help", "/h")
USAGE = "/help"
DESCRIPTION = "显示可用命令"


def configure(_parser: argparse.ArgumentParser) -> None:
    """/help 无需额外参数。"""


async def handle(_context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    """从注册表收集所有命令的用法与描述，拼接为帮助文本。"""
    from src.localhost.registry import command_specs

    text = "\n".join(f"{spec.usage:<58} {spec.description}" for spec in command_specs())
    return CommandResult(ok=True, text=text)
