"""从冻结 Assembly 创建进程门面，并完成认知唤起端口接线。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import (
    TREE_LAUNCHER_BINDINGS,
    AgentCatalog,
    AgentTreeRunner,
    RuntimeConfig,
    TerminalConsole,
    WorldJournal,
)
from src.runtime.core import AuroraRuntime

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.kernel import Assembly


def create_runtime(assembly: Assembly, *, output: Callable[[str], None] = print) -> AuroraRuntime:
    """从 Assembly 取出实际协作者创建门面，再绑定全部 TreeLauncher 贡献。"""
    runtime = AuroraRuntime(
        assembly,
        runner=assembly.get(AgentTreeRunner),
        agents=assembly.get(AgentCatalog),
        root=assembly.settings.resolve(RuntimeConfig),
        console=assembly.get(TerminalConsole),
        world=assembly.get(WorldJournal),
        output=output,
    )
    for bind in assembly.contributions(TREE_LAUNCHER_BINDINGS):
        bind(runtime)
    return runtime
