"""命令注册、校验、argparse 装配与分派：命令层组合根。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Required, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

_REPLACEMENTS = {
    "usage:": "用法：",
    "positional arguments:": "参数：",
    "options:": "选项：",
    "show this help message and exit": "显示帮助并退出",
}
_SPEC_FIELDS = frozenset({"name", "help", "options", "args", "subcommands"})


class SubcommandSpec(TypedDict, total=False):
    help: str
    options: dict[str, str | dict[str, Any]]
    args: dict[str, str]
    subcommands: dict[str, SubcommandSpec]


class CommandSpec(SubcommandSpec):
    name: Required[str]


type CommandBinding = tuple[CommandSpec, Callable[[argparse.Namespace], int]]


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


def _validate_spec(spec: SubcommandSpec, label: str) -> None:
    unexpected = set(spec) - _SPEC_FIELDS
    if unexpected:
        raise ValueError(f"{label} 包含未知字段：{', '.join(sorted(unexpected))}")
    _validate_options(spec.get("options"), label)
    for arg in spec.get("args", {}):
        if not arg.strip():
            raise ValueError(f"{label} 包含空位置参数名")
    for name, sub_spec in spec.get("subcommands", {}).items():
        if not name.strip():
            raise ValueError(f"{label} 包含空子命令名")
        _validate_spec(sub_spec, f"{label} {name}")


def _validate_options(options: dict[str, str | dict[str, Any]] | None, label: str) -> None:
    if options is None:
        return
    for flag, option in options.items():
        if not flag.startswith("-"):
            raise ValueError(f"{label} 的选项必须以 - 开头：{flag!r}")
        if isinstance(option, str):
            if not option.strip():
                raise ValueError(f"{label} 的选项帮助文本不能为空：{flag}")
        elif not isinstance(option, dict):
            raise ValueError(f"{label} 的选项必须是帮助文本或 add_argument 字典：{flag}")


@dataclass(frozen=True, slots=True)
class CommandRegistry:
    """注册完成的命令目录；构建时校验命令名称、规格结构与执行器绑定。"""

    entries: tuple[CommandBinding, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        names: set[str] = set()
        for spec, executor in self.entries:
            name = spec.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("命令名称不能为空")
            if name in names:
                raise ValueError(f"命令重复注册：{name}")
            names.add(name)
            _validate_spec(spec, name)
            if not callable(executor):
                raise ValueError(f"命令 {name} 必须绑定可调用执行器")


def build_registry(bindings: Iterable[CommandBinding]) -> CommandRegistry:
    """把命令目录的显式元组注册固化为校验过的只读目录。"""
    return CommandRegistry(tuple(bindings))


def build_parser(registry: CommandRegistry) -> argparse.ArgumentParser:
    """构建顶层解析器，并注册目录中的全部命令与子命令。"""
    parser: argparse.ArgumentParser = _ChineseArgumentParser(prog="aurora", description="AuroraBot 运行时")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="项目根目录")
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
        parser.add_argument(name, help=str(help_text))
    subcommands = spec.get("subcommands", {})
    if subcommands:
        actions = parser.add_subparsers(dest="subcommand")
        for name, sub_spec in subcommands.items():
            _apply_spec(actions.add_parser(name, help=sub_spec.get("help")), sub_spec, executor)
    else:
        parser.set_defaults(executor=executor)


def run(argv: Sequence[str] | None = None, *, registry: CommandRegistry) -> int:
    """按目录构建解析器，解析输入并分派到命令执行器。"""
    parser = build_parser(registry)
    arguments = parser.parse_args(argv)
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
