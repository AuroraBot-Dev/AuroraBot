"""CLI 命令目录；按文件名自动发现命令模块。

每个模块只声明一个 COMMAND 字典（名称、帮助、布尔选项、位置参数与子命令）和 execute 执行器；
aurora.commander 统一校验、装配 argparse 并分派。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aurora.commander import CommandSpec, SubcommandSpec, build_registry
from aurora.utils.modules import discover_modules

if TYPE_CHECKING:
    from aurora.commander import CommandBinding

COMMAND_SPECS = tuple(
    cast(
        "CommandBinding",
        (
            getattr(module, "COMMAND", None),
            getattr(module, "execute", None),
        ),
    )
    for module in discover_modules(
        __name__,
        tuple(str(path) for path in __path__),
    )
)

DEFAULT_REGISTRY = build_registry(COMMAND_SPECS)

__all__ = ["COMMAND_SPECS", "DEFAULT_REGISTRY", "CommandSpec", "SubcommandSpec"]
