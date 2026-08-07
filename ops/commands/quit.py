"""进程级 ``/quit`` 运行时命令的实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import (
    CommandControl,
    CommandResult,
)

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/quit", "/exit", "/q")
USAGE = "/quit"
DESCRIPTION = "优雅停止 Aurora 进程"


def configure(_parser: argparse.ArgumentParser) -> None:
    """/quit 无需额外参数。"""


async def handle(_context: CommandContext, _arguments: argparse.Namespace) -> CommandResult:
    """返回 SHUTDOWN_PROCESS 控制指令以触发进程优雅退出。"""
    return CommandResult(ok=True, text="Aurora 正在退出。", control=CommandControl.SHUTDOWN_PROCESS)
