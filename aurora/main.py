"""AuroraBot 项目命令的统一注册与分派入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from aurora.commands import COMMAND_REGISTRARS

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class _ChineseArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        return _translate_argparse(super().format_help())

    def format_usage(self) -> str:
        return _translate_argparse(super().format_usage())


def _translate_argparse(text: str) -> str:
    replacements = {
        "usage:": "用法：",
        "positional arguments:": "位置参数：",
        "options:": "选项：",
        "show this help message and exit": "显示帮助并退出",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = _ChineseArgumentParser(prog="aurora", description="AuroraBot 运行时")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="项目根目录")
    subparsers = cast(
        "argparse._SubParsersAction[argparse.ArgumentParser]",
        parser.add_subparsers(dest="command"),
    )
    for register in COMMAND_REGISTRARS:
        register(subparsers)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    executor = getattr(arguments, "executor", None)
    if executor is None:
        parser.print_help()
        return 0
    return cast("Callable[[argparse.Namespace], int]", executor)(arguments)


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
