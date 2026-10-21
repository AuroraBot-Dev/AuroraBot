"""CLI 命令目录；按文件名自动发现命令模块。

每个模块只声明一个 COMMAND 字典（名称、帮助、布尔选项、位置参数与子命令）和 execute 执行器；
aurora_cli.commander 统一校验、装配 argparse 并分派。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aurora_cli.commander import build_registry
from aurora_cli.contracts.command import CommandSpec, SubcommandSpec
from aurora_cli.utils.modules import discover_modules

if TYPE_CHECKING:
    from types import ModuleType

    from aurora_cli.contracts.command import CommandBinding


def _command_binding(module: ModuleType) -> CommandBinding:
    spec = getattr(module, "COMMAND", None)
    executor = getattr(module, "execute", None)
    if not isinstance(spec, dict):
        raise TypeError(f"命令模块必须导出 COMMAND：{module.__name__}")
    if not callable(executor):
        raise TypeError(f"命令模块必须导出可调用 execute：{module.__name__}")
    return cast("CommandBinding", (spec, executor))


COMMAND_SPECS = tuple(
    _command_binding(module)
    for module in discover_modules(
        __name__,
        tuple(str(path) for path in __path__),
    )
)

DEFAULT_REGISTRY = build_registry(COMMAND_SPECS)

__all__ = ["COMMAND_SPECS", "DEFAULT_REGISTRY", "CommandSpec", "SubcommandSpec"]
