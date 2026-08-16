"""所有 Aurora 进程命令的单一 argparse 入口点。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aurora.commands import check, donk, start

if TYPE_CHECKING:
    from collections.abc import Sequence

_COMMAND_MODULES = (check, donk, start)


def register_commands(subparsers: Any) -> None:
    """将所有已声明的命令模块注册到 argparse 子解析器中。"""
    for module in _COMMAND_MODULES:
        module.register(subparsers)


def build_parser() -> argparse.ArgumentParser:
    """构建包含所有 Aurora 子命令的顶层参数解析器。"""
    parser = argparse.ArgumentParser(prog="aurora", description="AuroraBot CLI")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="配置运行根目录")
    parser.add_argument("--profile", type=str, default=None, help="配置运行档案")
    register_commands(parser.add_subparsers(dest="command", required=True))
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """解析命令行参数并分发到对应子命令执行器。"""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    return arguments.executor(arguments)


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
