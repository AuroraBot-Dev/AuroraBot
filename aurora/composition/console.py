"""构造并导出 ``src.console`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.composition.world import WORLD_JOURNAL
from src.console import TerminalConsole

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

TERMINAL_CONSOLE = InstanceKey[TerminalConsole]("console.terminal")


def register(context: CompositionContext) -> None:
    context.provide(TERMINAL_CONSOLE, TerminalConsole(context.require(WORLD_JOURNAL)))
