"""``aurora_bot.runtime`` 的自描述模块：提供进程门面工厂。"""

from __future__ import annotations

from aurora_bot.contracts import COGNITION_BINDINGS, FRONT_BINDINGS
from aurora_bot.contracts.scope import ScopeDeclaration, ScopeKind
from aurora_bot.kernel import ModuleContext, module
from aurora_bot.runtime.events import RUNTIME_SCOPE
from aurora_bot.runtime.factory import RuntimeFactory, create_runtime


@module(
    name="runtime",
    provides="runtime",
    requires=("engine", "agents", "world", "bot", "operations"),
    consumes=(COGNITION_BINDINGS, FRONT_BINDINGS),
    declares=(COGNITION_BINDINGS, FRONT_BINDINGS),
    scopes=ScopeDeclaration(RUNTIME_SCOPE, ScopeKind.RESOURCE, "通过 Bot 运行门面直接提交的文本输入。"),
)
def build(_context: ModuleContext) -> RuntimeFactory:
    return create_runtime


MODULE = build
