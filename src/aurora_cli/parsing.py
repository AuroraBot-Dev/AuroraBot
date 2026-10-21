from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast, overload

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora_cli.contracts.command import CommandRegistry, SubcommandSpec

_REPLACEMENTS = {
    "usage:": "用法：",
    "positional arguments:": "参数：",
    "options:": "选项：",
    "show this help message and exit": "显示帮助并退出",
}


class _ChineseArgumentParser(argparse.ArgumentParser):
    forward_all = False

    @overload
    def parse_known_args(
        self, args: Iterable[str] | None = None, namespace: None = None
    ) -> tuple[argparse.Namespace, list[str]]: ...

    @overload
    def parse_known_args[T](self, args: Iterable[str] | None, namespace: T) -> tuple[T, list[str]]: ...

    @overload
    def parse_known_args[T](self, *, namespace: T) -> tuple[T, list[str]]: ...

    def parse_known_args(self, args: Iterable[str] | None = None, namespace: object = None) -> tuple[object, list[str]]:
        namespace = namespace if namespace is not None else argparse.Namespace()
        if not self.forward_all:
            return super().parse_known_args(args, namespace)
        # 纯透传叶子没有自己的参数；包括帮助和同名全局选项在内，均归目标程序解释。
        arguments, unknown = super().parse_known_args([], namespace)
        cast("argparse.Namespace", arguments).passthrough = list(sys.argv[1:] if args is None else args)
        return arguments, unknown

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
    parser: _ChineseArgumentParser,
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
            parser.forward_all = not spec.get("options") and not spec.get("args")
        parser.set_defaults(executor=executor)


def build_bootstrap_parser() -> argparse.ArgumentParser:
    parser = _ChineseArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("-r", "--root", type=Path, default=Path.cwd())
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument("remaining", nargs=argparse.REMAINDER)
    return parser
