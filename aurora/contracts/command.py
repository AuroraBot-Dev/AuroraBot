"""命令契约：CLI 命令规格、执行器绑定与注册目录值对象。

供 ``aurora.commands`` 各命令模块与 ``aurora.commander`` 装配逻辑共享；
校验只描述规格结构，不涉及 argparse 解析与分派。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Required, TypedDict

_SPEC_FIELDS = frozenset({"name", "help", "options", "args", "subcommands", "passthrough"})


class SubcommandSpec(TypedDict, total=False):
    help: str
    options: dict[str, str | dict[str, Any]]
    args: dict[str, str | dict[str, Any]]
    passthrough: str
    subcommands: dict[str, SubcommandSpec]


class CommandSpec(SubcommandSpec):
    name: Required[str]


type CommandBinding = tuple[CommandSpec, Callable[[argparse.Namespace], int]]


def _validate_spec(spec: SubcommandSpec, label: str) -> None:
    unexpected = set(spec) - _SPEC_FIELDS
    if unexpected:
        raise ValueError(f"{label} 包含未知字段：{', '.join(sorted(unexpected))}")
    _validate_options(spec.get("options"), label)
    _validate_args(spec.get("args"), label)
    passthrough = spec.get("passthrough")
    if passthrough is not None and not passthrough.strip():
        raise ValueError(f"{label} 的透传参数帮助文本不能为空")
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


def _validate_args(args: dict[str, str | dict[str, Any]] | None, label: str) -> None:
    if args is None:
        return
    for name, arg in args.items():
        if not name.strip():
            raise ValueError(f"{label} 包含空位置参数名")
        if isinstance(arg, str):
            if not arg.strip():
                raise ValueError(f"{label} 的位置参数帮助文本不能为空：{name}")
        elif not isinstance(arg, dict):
            raise ValueError(f"{label} 的位置参数必须是帮助文本或 add_argument 字典：{name}")


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
