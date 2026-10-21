"""从冻结 Assembly 创建进程门面，并完成认知唤起端口接线。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from aurora_bot.contracts import FRONT_BINDINGS, TREE_LAUNCHER_BINDINGS
from aurora_bot.contracts.pkgs.agents import AgentCatalog
from aurora_bot.contracts.pkgs.bot import BotStateStore
from aurora_bot.contracts.pkgs.engine import AgentTreeRunner
from aurora_bot.contracts.pkgs.operations import OperationRegistry
from aurora_bot.contracts.pkgs.world import WorldJournal
from aurora_bot.runtime.config import RuntimeConfig
from aurora_bot.runtime.core import AuroraRuntime

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_bot.kernel import Assembly


class RuntimeFactory(Protocol):
    """从冻结 ``Assembly`` 创建进程门面的可调用契约。"""

    def __call__(self, assembly: Assembly, *, output: Callable[[str], None] = ...) -> AuroraRuntime: ...


def create_runtime(assembly: Assembly, *, output: Callable[[str], None] = print) -> AuroraRuntime:
    """从 Assembly 取出实际协作者创建门面，再绑定全部 TreeLauncher 贡献。"""
    agents = assembly.get(AgentCatalog)
    root = assembly.settings.resolve(RuntimeConfig)
    if root.agent not in agents.ids:
        raise ValueError(f"root 引用了未知 Agent definition：{root.agent}")
    runtime = AuroraRuntime(
        assembly,
        runner=assembly.get(AgentTreeRunner),
        agents=agents,
        root=root,
        world=assembly.get(WorldJournal),
        operations=assembly.get(OperationRegistry),
        bot_id=assembly.get(BotStateStore).bot_id,
        output=output,
        front_bindings=assembly.contributions(FRONT_BINDINGS),
    )
    for bind in assembly.contributions(TREE_LAUNCHER_BINDINGS):
        bind(runtime)
    return runtime
