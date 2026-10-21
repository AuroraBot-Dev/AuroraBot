from __future__ import annotations

import sys
from typing import TYPE_CHECKING, cast

from aurora_cli.contracts.command import CommandBinding, CommandRegistry, CommandSpec, SubcommandSpec
from aurora_cli.parsing import build_bootstrap_parser, build_parser
from aurora_cli.plugins.catalog import load_plugins
from aurora_cli.utils.process import EXIT_CONFIG_ERROR
from aurora_cli.utils.project import get_running_version

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Iterable, Sequence


def build_registry(bindings: Iterable[CommandBinding]) -> CommandRegistry:
    return CommandRegistry(tuple(bindings))


def run(argv: Sequence[str] | None = None, *, registry: CommandRegistry | None = None) -> int:
    if registry is None:
        bootstrap = build_bootstrap_parser()
        early, unknown = bootstrap.parse_known_args(argv)
        if early.version and not early.remaining and not unknown:
            return _show_version()
        try:
            registry = load_plugins(early.root).registry()
        except (OSError, ImportError, TypeError, ValueError) as error:
            sys.stderr.write(f"CLI 插件加载失败：{error}\n")
            return EXIT_CONFIG_ERROR
    parser = build_parser(registry)
    arguments = parser.parse_args(argv)
    if getattr(arguments, "version", False):
        return _show_version()
    executor = getattr(arguments, "executor", None)
    if executor is None:
        getattr(arguments, "help_parser", parser).print_help()
        return 0
    return cast("Callable[[argparse.Namespace], int]", executor)(arguments)


def main(argv: Sequence[str] | None = None, *, registry: CommandRegistry | None = None) -> None:
    raise SystemExit(run(argv, registry=registry))


def _show_version() -> int:
    sys.stdout.write(f"AuroraBot {get_running_version()}\n")
    return 0


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
