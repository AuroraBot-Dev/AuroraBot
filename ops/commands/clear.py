"""Console ``/clear`` 运行时命令的实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import (
    CommandControl,
    CommandResult,
)

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/clear", "/cls")
USAGE = "/clear"
DESCRIPTION = "清空 Console（别名 /cls）"


def configure(_parser: argparse.ArgumentParser) -> None:
    """/clear 无需额外参数。"""


async def handle(_context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    """返回 CLEAR_CONSOLE 控制指令以触发前端清屏。"""
    return CommandResult(ok=True, publish_reply=False, control=CommandControl.CLEAR_CONSOLE)
