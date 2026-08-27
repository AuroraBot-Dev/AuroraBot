"""AuroraBot 项目命令的统一注册与分派入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from aurora.commands import COMMAND_SPECS, CommandSpec, SubcommandSpec

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

REPLACEMENTS = {
    "usage:": "用法：",
    "positional arguments:": "参数：",
    "options:": "选项：",
    "show this help message and exit": "显示帮助并退出",
}


class _ChineseArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        return _translate_argparse(super().format_help())

    def format_usage(self) -> str:
        return _translate_argparse(super().format_usage())


def _translate_argparse(text: str) -> str:
    replacements = REPLACEMENTS
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _register_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    spec: CommandSpec,
    executor: Callable[[argparse.Namespace], int],
) -> None:
    """按命令规格装配一个子解析器；help_parser 指向本命令，执行器绑定到叶子解析器。"""
    parser = subparsers.add_parser(spec["name"], help=spec.get("help"))
    parser.set_defaults(help_parser=parser)
    _apply_spec(parser, spec, executor)


def _apply_spec(
    parser: argparse.ArgumentParser,
    spec: SubcommandSpec,
    executor: Callable[[argparse.Namespace], int],
) -> None:
    """递归装配布尔选项、位置参数与子命令；未提供子命令时叶子不存在，执行器保持未绑定。"""
    for flag, option in spec.get("options", {}).items():
        if isinstance(option, dict):
            parser.add_argument(flag, **cast("dict[str, Any]", option))
        else:
            parser.add_argument(flag, action="store_true", help=str(option))
    for name, help_text in spec.get("args", {}).items():
        parser.add_argument(name, help=str(help_text))
    subcommands = spec.get("subcommands", {})
    if subcommands:
        actions = parser.add_subparsers(dest="subcommand")
        for name, sub_spec in subcommands.items():
            _apply_spec(actions.add_parser(name, help=sub_spec.get("help")), sub_spec, executor)
    else:
        parser.set_defaults(executor=executor)


def build_parser() -> argparse.ArgumentParser:
    """构建顶层解析器，并注册全部命令与子命令。"""
    parser: argparse.ArgumentParser = _ChineseArgumentParser(prog="aurora", description="AuroraBot 运行时")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="项目根目录")
    subparsers = cast(
        "argparse._SubParsersAction[argparse.ArgumentParser]",
        parser.add_subparsers(dest="command"),
    )
    for spec, executor in COMMAND_SPECS:
        _register_command(subparsers, spec, executor)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    executor = getattr(arguments, "executor", None)
    if executor is None:
        getattr(arguments, "help_parser", parser).print_help()
        return 0
    return cast("Callable[[argparse.Namespace], int]", executor)(arguments)


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main(sys.argv[1:])
