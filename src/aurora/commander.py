"""命令组合根：校验命令规格，装配 argparse 解析器并分派执行。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from aurora.contracts.command import CommandBinding, CommandRegistry, CommandSpec, SubcommandSpec
from aurora.utils.project import get_running_version

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

_REPLACEMENTS = {
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
    replacements = _REPLACEMENTS
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def build_registry(bindings: Iterable[CommandBinding]) -> CommandRegistry:
    """固化命令目录的显式元组注册为校验过的只读目录。"""
    return CommandRegistry(tuple(bindings))


def build_parser(registry: CommandRegistry) -> argparse.ArgumentParser:
    """构建顶层解析器，并注册目录中的全部命令与子命令。"""
    parser: argparse.ArgumentParser = _ChineseArgumentParser(prog="aurora", description="AuroraBot 运行时")
    parser.add_argument("-v", "--version", action="store_true", help="显示版本并退出")
    parser.add_argument("-r", "--root", type=Path, default=Path.cwd(), help="项目根目录")
    subparsers = cast(
        "argparse._SubParsersAction[argparse.ArgumentParser]",
        parser.add_subparsers(dest="command"),
    )
    for spec, executor in registry.entries:
        _register_command(subparsers, spec, executor)
    return parser


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
        if isinstance(help_text, dict):
            parser.add_argument(name, **cast("dict[str, Any]", help_text))
        else:
            parser.add_argument(name, help=str(help_text))
    subcommands = spec.get("subcommands", {})
    if subcommands:
        actions = parser.add_subparsers(dest="subcommand")
        for name, sub_spec in subcommands.items():
            _apply_spec(actions.add_parser(name, help=sub_spec.get("help")), sub_spec, executor)
    else:
        passthrough = spec.get("passthrough")
        if passthrough is not None:
            parser.add_argument("passthrough", nargs=argparse.REMAINDER, help=str(passthrough))
        parser.set_defaults(executor=executor)


def run(argv: Sequence[str] | None = None, *, registry: CommandRegistry) -> int:
    """按目录构建解析器，解析输入并分派到命令执行器。"""
    parser = build_parser(registry)
    arguments = parser.parse_args(argv)
    if getattr(arguments, "version", False):
        sys.stdout.write(f"AuroraBot {get_running_version()}\n")
        return 0
    executor = getattr(arguments, "executor", None)
    if executor is None:
        getattr(arguments, "help_parser", parser).print_help()
        return 0
    return cast("Callable[[argparse.Namespace], int]", executor)(arguments)


def main(argv: Sequence[str] | None = None, *, registry: CommandRegistry) -> None:
    raise SystemExit(run(argv, registry=registry))


__all__ = [
    "CommandBinding",
    "CommandRegistry",
    "CommandSpec",
    "SubcommandSpec",
    "build_parser",
    "build_registry",
    "main",
    "run",
]
