"""``/log`` 终端日志命令的实现。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import CommandResult
from src.utils import (
    configure_console_logging,
    console_logging_status,
)

if TYPE_CHECKING:
    import argparse

    from src.contracts.event import CommandContext

NAMES = ("/log",)
USAGE = "/log [on|off] [--level <debug|info|warning|error|critical>]"
DESCRIPTION = "控制当前进程的终端日志"
LEVELS = ("debug", "info", "warning", "warn", "error", "critical")


def configure(parser: argparse.ArgumentParser) -> None:
    """配置 /log 命令参数：开关状态与日志级别。"""
    parser.add_argument("state", nargs="?", choices=("on", "off"))
    parser.add_argument("--level", type=str.lower, choices=LEVELS)


async def handle(_context: CommandContext, arguments: argparse.Namespace) -> CommandResult:
    """根据参数切换终端日志开关/级别并返回当前状态。"""
    if arguments.state is not None or arguments.level is not None:
        level = "WARNING" if arguments.level == "warn" else arguments.level
        configure_console_logging(
            enabled=None if arguments.state is None else arguments.state == "on",
            level=level,
        )
    status = console_logging_status()
    return CommandResult(ok=True, text=json.dumps(status, ensure_ascii=False), data=status)
