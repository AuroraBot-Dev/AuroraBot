"""框架内建工具目录；项目组合时按依赖传入并显式汇总。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.tools.builtin.wait import WAIT_TOOL, WaitTool
from aurora_bot.tools.builtin.world import (
    WORLD_READ_TOOL,
    WORLD_RUNS_TOOL,
    WORLD_SCOPES_TOOL,
    WorldReadTool,
    WorldRunsTool,
    WorldScopesTool,
)

if TYPE_CHECKING:
    from aurora_bot.contracts import ScopeCatalog, Tool
    from aurora_bot.contracts.pkgs.world import WorldReader

__all__ = [
    "WAIT_TOOL",
    "WORLD_READ_TOOL",
    "WORLD_RUNS_TOOL",
    "WORLD_SCOPES_TOOL",
    "WaitTool",
    "WorldReadTool",
    "WorldRunsTool",
    "WorldScopesTool",
    "builtin_tools",
]


def builtin_tools(
    *,
    journal: WorldReader,
    scopes: ScopeCatalog,
) -> tuple[Tool, ...]:
    """返回框架内建工具；外部工具由组合根追加到同一 ToolRegistry。"""
    return (
        WorldReadTool(journal),
        WorldScopesTool(scopes),
        WorldRunsTool(journal),
        WaitTool(),
    )
