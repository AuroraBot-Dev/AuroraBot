"""实现 ``aurora about``"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

NAME = "about"

_ABOUT = """\
                              ▄          ▄
▄▀▀█ █  █ █▀▀▀ █▀▀█ █▀▀▀ ▄▀▀█ █▀▀█ █▀▀█ ▀█▀▀
█░░█ █░░█ █    █░░█ █    █░░█ █░░█ █░░█  █░░
▀▀▀▀ ▀▀▀▀ ▀    ▀▀▀▀ ▀    ▀▀▀▀ ▀▀▀▀ ▀▀▀▀  ▀▀▀

AuroraBot
把想法交给智能体，把结果带回来。

AuroraBot 是一个轻量、可组合的自主智能体运行时。你可以让它理解目标、
调用工具、拆分工作，再把每一步的结果汇成一次完整的执行。

它适合用来：
  - 把重复的流程交给智能体处理
  - 让智能体使用工具完成实际工作
  - 组合多个角色，一起解决复杂问题

少一点手动切换，多一点自动完成。
四角色消息让对话、工具和协作各就各位。
"""


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(NAME, help="了解 AuroraBot")
    parser.set_defaults(executor=execute)


def execute(_arguments: argparse.Namespace) -> int:
    sys.stdout.write(_ABOUT)
    return 0
