"""``aurorabot.runtime`` 的自描述模块：提供进程门面工厂。"""

from __future__ import annotations

from aurorabot.contracts import FRONT_BINDINGS, TREE_LAUNCHER_BINDINGS
from aurorabot.contracts.pkgs.agents import AgentCatalog
from aurorabot.contracts.pkgs.bot import BotStateStore
from aurorabot.contracts.pkgs.engine import AgentTreeRunner
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.contracts.pkgs.world import WorldJournal
from aurorabot.contracts.scope import ScopeDeclaration, ScopeKind
from aurorabot.kernel import ModuleContext, module
from aurorabot.runtime.events import RUNTIME_SCOPE
from aurorabot.runtime.factory import RuntimeFactory, create_runtime


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
