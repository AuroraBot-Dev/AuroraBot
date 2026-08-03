"""Aurora CLI 进程级命令的声明式注册表。"""

from __future__ import annotations

from typing import Any

from aurora.commands import check, donk

COMMAND_MODULES = (check, donk)


def register_commands(subparsers: Any) -> None:
    """将所有已声明的命令模块注册到 argparse 子解析器中。"""
    for module in COMMAND_MODULES:
        module.register(subparsers)
