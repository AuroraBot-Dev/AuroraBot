"""声明 Bot 进程门面的实际依赖，并组合认知唤起端口的绑定。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aurora.composer import InstanceKey, PackageSpec
from aurora.configuration.runtime import RUNTIME_CONFIG
from aurora.contributions import TREE_LAUNCHER_BINDINGS
from aurora.runtime.core import AuroraRuntime

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora.composer import AuroraAssembly, CompositionContext
    from src.agents import AgentCatalog
    from src.console import TerminalConsole
    from src.contracts import WorldJournal
    from src.engine import AgentTreeRunner

type RuntimeFactory = Callable[[AuroraAssembly, Callable[[str], None]], AuroraRuntime]

RUNTIME_FACTORY = InstanceKey[RuntimeFactory]("runtime.factory")

ENGINE_RUNNER_NAME = "engine.runner"
AGENTS_NAME = "agents.catalog"
TERMINAL_CONSOLE_NAME = "console.terminal"
WORLD_JOURNAL_NAME = "world.journal"


def construct(context: CompositionContext) -> None:
    """捕获已构造协作者；门面在 Assembly 冻结后创建并完成端口接线。"""
    runner = cast("AgentTreeRunner", context.require_name(ENGINE_RUNNER_NAME))
    agents = cast("AgentCatalog", context.require_name(AGENTS_NAME))
    root = context.config.get(RUNTIME_CONFIG)
    console = cast("TerminalConsole", context.require_name(TERMINAL_CONSOLE_NAME))
    world = cast("WorldJournal", context.require_name(WORLD_JOURNAL_NAME))
    bindings = context.contributions(TREE_LAUNCHER_BINDINGS)

    def create(assembly: AuroraAssembly, output: Callable[[str], None]) -> AuroraRuntime:
        runtime = AuroraRuntime(
            assembly,
            runner=runner,
            agents=agents,
            root=root,
            console=console,
            world=world,
            output=output,
        )
        for bind in bindings:
            bind(runtime)
        return runtime

    context.provide(RUNTIME_FACTORY, create)


PACKAGE_SPEC = PackageSpec(
    key=RUNTIME_FACTORY,
    provides=(RUNTIME_FACTORY,),
    requires=(ENGINE_RUNNER_NAME, AGENTS_NAME, TERMINAL_CONSOLE_NAME, WORLD_JOURNAL_NAME),
    consumes=(TREE_LAUNCHER_BINDINGS,),
    register=construct,
)
