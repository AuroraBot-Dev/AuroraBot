"""框架内建工具目录；项目组合时按依赖传入并显式汇总。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.tools.builtin.delegate import DELEGATE_TOOL, DelegateTool
from aurora_bot.tools.builtin.wait import WAIT_TOOL, WaitTool
from aurora_bot.tools.builtin.world import (
    WORLD_READ_TOOL,
    WORLD_SCOPES_TOOL,
    WORLD_TREES_TOOL,
    WorldReadTool,
    WorldScopesTool,
    WorldTreesTool,
)

if TYPE_CHECKING:
    from aurora_bot.contracts import ScopeCatalog, Tool
    from aurora_bot.contracts.pkgs.agents import AgentCatalog
    from aurora_bot.contracts.pkgs.world import WorldReader

__all__ = [
    "DELEGATE_TOOL",
    "WAIT_TOOL",
    "WORLD_READ_TOOL",
    "WORLD_SCOPES_TOOL",
    "WORLD_TREES_TOOL",
    "DelegateTool",
    "WaitTool",
    "WorldReadTool",
    "WorldScopesTool",
    "WorldTreesTool",
    "builtin_tools",
]


def builtin_tools(
    *,
    agents: AgentCatalog,
    journal: WorldReader,
    scopes: ScopeCatalog,
) -> tuple[Tool, ...]:
    """返回框架内建工具；外部工具由组合根追加到同一 ToolRegistry。"""
    return (
        DelegateTool(agents),
        WorldReadTool(journal),
        WorldScopesTool(scopes),
        WorldTreesTool(journal),
        WaitTool(),
    )
