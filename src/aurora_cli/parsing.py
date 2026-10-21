from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_cli.contracts.command import CommandRegistry, SubcommandSpec

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
    for source, target in _REPLACEMENTS.items():
        text = text.replace(source, target)
    return text


def build_parser(registry: CommandRegistry) -> argparse.ArgumentParser:
    parser = _ChineseArgumentParser(prog="aurora", description="AuroraBot CLI", allow_abbrev=False)
    parser.add_argument("-v", "--version", action="store_true", help="查看版本")
    parser.add_argument("-r", "--root", type=Path, default=Path.cwd(), help="指定项目根目录")
    subparsers = parser.add_subparsers(dest="command")
    for spec, executor in registry.entries:
        command = subparsers.add_parser(spec["name"], help=spec.get("help"), allow_abbrev=False)
        _apply_spec(command, spec, executor)
    return parser


def _apply_spec(
    parser: argparse.ArgumentParser,
    spec: SubcommandSpec,
    executor: Callable[[argparse.Namespace], int],
) -> None:
    parser.set_defaults(help_parser=parser)
    for flag, option in spec.get("options", {}).items():
        if isinstance(option, dict):
            parser.add_argument(flag, **option)
        else:
            parser.add_argument(flag, action="store_true", help=option)
    for name, help_text in spec.get("args", {}).items():
        if isinstance(help_text, dict):
            parser.add_argument(name, **help_text)
        else:
            parser.add_argument(name, help=help_text)
    subcommands = spec.get("subcommands", {})
    if subcommands:
        actions = parser.add_subparsers(dest="subcommand")
        for name, sub_spec in subcommands.items():
            child = actions.add_parser(name, help=sub_spec.get("help"), allow_abbrev=False)
            _apply_spec(child, sub_spec, executor)
    else:
        passthrough = spec.get("passthrough")
        if passthrough is not None:
            parser.add_argument("passthrough", nargs=argparse.REMAINDER, help=passthrough)
        parser.set_defaults(executor=executor)


def build_bootstrap_parser() -> argparse.ArgumentParser:
    parser = _ChineseArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("-r", "--root", type=Path, default=Path.cwd())
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument("remaining", nargs=argparse.REMAINDER)
    return parser
