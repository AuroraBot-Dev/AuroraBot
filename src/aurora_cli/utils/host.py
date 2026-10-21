"""把命令声明接到 namespace 与调用点宿主，命令名仍由 CLI 决定。"""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING

from aurora_kernel import Context, Host, Namespace, namespace

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable

    from aurora_cli.contracts.command import CommandBinding


def command_modules(bindings: Iterable[CommandBinding]) -> tuple[Namespace, ...]:
    return tuple(_command_module(binding) for binding in bindings)


def _command_module(binding: CommandBinding) -> Namespace:
    spec, execute = binding
    name = f"aurora.cli.commands.{spec['name']}"

    @namespace(name)
    def command(ctx: Context) -> None:
        ctx[name]["command"] = spec

    @command.callpoint("execute")
    def invoke(_ctx: Context, arguments: argparse.Namespace) -> int:
        return execute(arguments)

    return command


def bind_commands(bindings: Iterable[CommandBinding]) -> tuple[CommandBinding, ...]:
    """每次执行使用独立 ctx，命令发现与基本帮助不启动 Bot。"""
    listed = tuple(bindings)
    modules = command_modules(listed)
    return tuple(_binding(binding, modules) for binding in listed)


def _binding(binding: CommandBinding, modules: tuple[Namespace, ...]) -> CommandBinding:
    spec, execute = binding
    target = f"aurora.cli.commands.{spec['name']}:execute"

    @wraps(execute)
    def invoke(arguments: argparse.Namespace) -> int:
        host = Host(modules).build()
        return host.call(target, arguments)

    return spec, invoke
