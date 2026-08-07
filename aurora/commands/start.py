"""实现 ``aurora start`` 子命令。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.contracts.configuration import PLATFORM_NAMES

if TYPE_CHECKING:
    import argparse

NAME = "start"


def register(subparsers: Any) -> None:
    """向子解析器注册 start 命令及其 headless/platform 选项。"""
    parser = subparsers.add_parser(NAME, help="启动 Aurora 运行时")
    parser.add_argument("--headless", action="store_true", help="启用无头模式")
    parser.add_argument(
        "--platform", action="append", choices=sorted(PLATFORM_NAMES), metavar="NAME", help="启用指定平台"
    )
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    """按指定的平台集合启动 Aurora 运行时并等待其停止。"""
    from aurora.runtime import run_runtime

    selected = frozenset(arguments.platform) if arguments.platform else None
    asyncio.run(run_runtime(selected, headless=arguments.headless))
    return 0
