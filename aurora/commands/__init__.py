"""CLI 命令目录；新增命令在此显式注册。

每个模块只声明一个 COMMAND 字典（名称、帮助、布尔选项、位置参数与子命令）和 execute 执行器；
本目录以 (COMMAND, execute) 显式元组登记，aurora.commander 统一校验、装配 argparse 并分派。
"""

from __future__ import annotations

from aurora.commander import CommandSpec, SubcommandSpec, build_registry
from aurora.commands import (
    about,
    check,
    config,
    donk,
    setup,
    start,
)

COMMAND_SPECS = (
    (start.COMMAND, start.execute),
    (about.COMMAND, about.execute),
    (check.COMMAND, check.execute),
    (config.COMMAND, config.execute),
    (donk.COMMAND, donk.execute),
    (setup.COMMAND, setup.execute),
)

DEFAULT_REGISTRY = build_registry(COMMAND_SPECS)

__all__ = ["COMMAND_SPECS", "DEFAULT_REGISTRY", "CommandSpec", "SubcommandSpec"]
