"""所有 Aurora 进程命令的单一 argparse 入口点。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from aurora.registry import register_commands
from src.config import init as init_config

if TYPE_CHECKING:
    from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """构建包含所有 Aurora 子命令的顶层参数解析器。

    顶层不承载任何执行行为：裸 ``aurora`` 只展示用法，具体命令通过子命令分发。
    """
    parser = argparse.ArgumentParser(prog="aurora", description="AuroraBot CLI")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="配置与数据根目录")
    parser.add_argument("--profile", type=str, default=None, help="配置运行档案")
    register_commands(parser.add_subparsers(dest="command", required=True))
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """解析命令行参数、加载配置并分发到对应子命令执行器。"""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command != "check":
        init_config(arguments.root, arguments.profile)
    return arguments.executor(arguments)


def main(argv: Sequence[str] | None = None) -> None:
    """CLI 顶层入口，通过 SystemExit 返回退出码。"""
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
