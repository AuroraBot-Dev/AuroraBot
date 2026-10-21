"""``aurora_bot.runtime`` 的自描述模块：提供进程门面工厂。"""

from __future__ import annotations

from aurora_bot.contracts import FRONT_BINDINGS, TREE_LAUNCHER_BINDINGS
from aurora_bot.contracts.pkgs.agents import AgentCatalog
from aurora_bot.contracts.pkgs.bot import BotStateStore
from aurora_bot.contracts.pkgs.engine import AgentTreeRunner
from aurora_bot.contracts.pkgs.operations import OperationRegistry
from aurora_bot.contracts.pkgs.world import WorldJournal
from aurora_bot.contracts.scope import ScopeDeclaration, ScopeKind
from aurora_bot.kernel import ModuleContext, module
from aurora_bot.runtime.events import RUNTIME_SCOPE
from aurora_bot.runtime.factory import RuntimeFactory, create_runtime


@module(
    name="runtime",
    provides=RuntimeFactory,
    requires=(AgentTreeRunner, AgentCatalog, WorldJournal, BotStateStore, OperationRegistry),
    consumes=(TREE_LAUNCHER_BINDINGS, FRONT_BINDINGS),
    declares=(TREE_LAUNCHER_BINDINGS, FRONT_BINDINGS),
    scopes=ScopeDeclaration(RUNTIME_SCOPE, ScopeKind.RESOURCE, "通过 Bot 运行门面直接提交的文本输入。"),
)
def build(_context: ModuleContext) -> RuntimeFactory:
    return create_runtime


MODULE = build
