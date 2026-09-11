"""``src.console`` 的自描述模块。"""

from __future__ import annotations

from src.console import TerminalConsole
from src.contracts import TerminalConsole as TerminalConsolePort
from src.contracts import WorldWriter
from src.kernel import ModuleContext, module


@module(name="console", provides=TerminalConsolePort, requires=(WorldWriter,))
def build(context: ModuleContext) -> TerminalConsolePort:
    return TerminalConsole(context.get(WorldWriter))


MODULE = build
