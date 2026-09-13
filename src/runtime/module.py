"""``src.runtime`` 的自描述模块：提供进程门面工厂。"""

from __future__ import annotations

from src.contracts import TREE_LAUNCHER_BINDINGS, AgentCatalog, AgentTreeRunner, TerminalConsole, WorldJournal
from src.kernel import ModuleContext, module
from src.runtime.factory import RuntimeFactory, create_runtime


@module(
    name="runtime",
    provides=RuntimeFactory,
    requires=(AgentTreeRunner, AgentCatalog, TerminalConsole, WorldJournal),
    consumes=(TREE_LAUNCHER_BINDINGS,),
    declares=(TREE_LAUNCHER_BINDINGS,),
)
def build(_context: ModuleContext) -> RuntimeFactory:
    return create_runtime


MODULE = build
