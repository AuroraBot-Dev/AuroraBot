"""``/pump`` 运行时命令的实现。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.localhost.command_types import CommandResult

if TYPE_CHECKING:
    import argparse

    from src.localhost.command_types import CommandContext

NAMES = ("/pump", "/p")
USAGE = "/pump [1-100]"
DESCRIPTION = "推进 Agent turns"


def configure(parser: argparse.ArgumentParser) -> None:
    """配置 /pump 命令参数：turns 数量（1-100，默认 1）。"""
    parser.add_argument("turns", nargs="?", default=1, type=int, choices=range(1, 101))


async def handle(context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    """执行指定轮次的 Kernel 泵取并返回结构化的执行结果。"""
    data = await context.runtime.pump(arguments.turns)
    return CommandResult(ok=True, text=json.dumps(data, ensure_ascii=False), data=data)
