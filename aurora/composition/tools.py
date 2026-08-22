"""构造并导出 ``src.tools`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.composition.agents import AGENTS
from aurora.composition.world import WORLD_JOURNAL
from src.tools import DelegateTool, ToolRegistry, WorldReadTool, WorldTreesTool

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

TOOLS = InstanceKey[ToolRegistry]("tools.registry")


def register(context: CompositionContext) -> None:
    """把框架内建工具与外部注入工具组成唯一目录。"""
    journal = context.require(WORLD_JOURNAL)
    context.provide(
        TOOLS,
        ToolRegistry(
            (
                DelegateTool(context.require(AGENTS)),
                WorldReadTool(journal),
                WorldTreesTool(journal),
                *context.tools,
            )
        ),
    )
