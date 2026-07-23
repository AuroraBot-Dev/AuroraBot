"""所有 Aurora 进程命令的单一 argparse 入口点。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from aurora.registry import register_commands

if TYPE_CHECKING:
    from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """构建包含所有 Aurora 子命令的顶层参数解析器。"""
    parser = argparse.ArgumentParser(prog="aurora", description="AuroraBot CLI")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="配置与数据根目录")
    parser.add_argument("--profile", type=str, default="prod", help="配置运行档案")
    parser.add_argument("--console", action="store_true", help="启用 Console 平台")
    parser.add_argument("--dashboard", action="store_true", help="启用 Dashboard 平台")
    parser.add_argument("--mcp", action="store_true", help="启用 MCP 平台")
    parser.add_argument("--headless", action="store_true", help="不启用外部平台")
    register_commands(parser.add_subparsers(dest="command"))
    parser.set_defaults(executor=_execute_runtime)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """解析命令行参数、验证平台组合并分发到对应执行器。"""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    selected = frozenset(name for name in ("console", "dashboard", "mcp") if getattr(arguments, name))
    if arguments.command == "check":
        if arguments.headless or selected:
            parser.error("platform selection options cannot be used with check")
    elif arguments.headless and selected:
        parser.error("--headless cannot be combined with --console, --dashboard, or --mcp")
    arguments.platforms = frozenset() if arguments.headless else selected or None
    return arguments.executor(arguments)


def _execute_runtime(arguments: argparse.Namespace) -> int:
    """根据解析后的参数启动 Aurora 运行时。"""
    from aurora.runtime import run_runtime

    asyncio.run(run_runtime(arguments.root, arguments.profile, arguments.platforms))
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """CLI 顶层入口，通过 SystemExit 返回退出码。"""
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
