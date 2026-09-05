"""构造并导出 ``src.console`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aurora.composer import InstanceKey, PackageSpec
from src.console import TerminalConsole

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from src.contracts import WorldWriter

WORLD_JOURNAL_NAME = "world.journal"

TERMINAL_CONSOLE = InstanceKey[TerminalConsole]("console.terminal")


def construct(context: CompositionContext) -> None:
    """构造并注册 ``src.console`` 的项目实例。"""
    world = cast("WorldWriter", context.require_name(WORLD_JOURNAL_NAME))
    context.provide(TERMINAL_CONSOLE, TerminalConsole(world))


PACKAGE_SPEC = PackageSpec(
    key=TERMINAL_CONSOLE,
    provides=(TERMINAL_CONSOLE,),
    requires=(WORLD_JOURNAL_NAME,),
    register=construct,
)
