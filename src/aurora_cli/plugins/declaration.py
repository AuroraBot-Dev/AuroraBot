"""单命令与单配置声明的便捷适配；组合插件可直接使用 CliPlugin。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from aurora_cli.contracts.plugin import CliPlugin, CommandContribution, ConfigContribution, ConfigFile
from aurora_kernel import Context, namespace

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from aurora_cli.contracts.command import CommandSpec
    from aurora_cli.contracts.config import ConfigSpec


def command_plugin(name: str, spec: CommandSpec, execute: Callable[[argparse.Namespace], int]) -> CliPlugin:
    """将普通命令接入 namespace 调用点，执行器只在用户选择命令后调用。"""

    @namespace(name)
    def module(ctx: Context) -> None:
        ctx[name]["command"] = spec

    @module.callpoint("execute")
    def invoke(_ctx: Context, arguments: argparse.Namespace) -> int:
        return execute(arguments)

    return CliPlugin(module, commands=(CommandContribution(spec, f"{name}:execute"),))


def config_plugin(name: str, spec: ConfigSpec[Any], directory: Path) -> CliPlugin:
    """同名 TOML 与 resources 随配置插件分发，目标路径来自配置声明。"""

    @namespace(name)
    def module(ctx: Context) -> None:
        ctx[name]["config"] = spec

    files = [ConfigFile(directory / f"{spec.name}.toml", spec.path)]
    resources = directory / "resources"
    destination = Path(spec.path).with_suffix("")
    for source in sorted(resources.rglob("*")):
        if source.is_file():
            files.append(ConfigFile(source, (destination / source.relative_to(resources)).as_posix()))
    return CliPlugin(module, configs=(ConfigContribution(spec, tuple(files)),))
