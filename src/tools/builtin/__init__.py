"""框架内建工具目录；项目组合时按依赖传入并显式汇总。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.tools.builtin.delegate import DELEGATE_TOOL, DelegateTool
from src.tools.builtin.wait import WAIT_TOOL, WaitTool
from src.tools.builtin.world import WORLD_READ_TOOL, WORLD_TREES_TOOL, WorldReadTool, WorldTreesTool

if TYPE_CHECKING:
    from src.agents import AgentCatalog
    from src.contracts import Tool, WorldJournal

__all__ = [
    "DELEGATE_TOOL",
    "WAIT_TOOL",
    "WORLD_READ_TOOL",
    "WORLD_TREES_TOOL",
    "DelegateTool",
    "WaitTool",
    "WorldReadTool",
    "WorldTreesTool",
    "builtin_tools",
]


def builtin_tools(*, agents: AgentCatalog, journal: WorldJournal) -> tuple[Tool, ...]:
    """返回框架内建工具；外部工具由组合根追加到同一 ToolRegistry。"""
    return (DelegateTool(agents), WorldReadTool(journal), WorldTreesTool(journal), WaitTool())
