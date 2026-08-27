"""构造并导出 ``src.tools`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.composition.agents import AGENTS
from aurora.composition.world import WORLD_JOURNAL
from src.tools import ToolRegistry
from src.tools.builtin import builtin_tools

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

TOOLS = InstanceKey[ToolRegistry]("tools.registry")


def register(context: CompositionContext) -> None:
    """组成框架内建工具与外部注入工具的唯一目录。"""
    journal = context.require(WORLD_JOURNAL)
    agents = context.require(AGENTS)
    context.provide(
        TOOLS,
        ToolRegistry((*builtin_tools(agents=agents, journal=journal), *context.tools)),
    )
