"""构造并导出 ``src.tools`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aurora.composer import InstanceKey, PackageSpec
from src.tools import ToolRegistry
from src.tools.builtin import builtin_tools

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from src.agents import AgentCatalog
    from src.contracts import Tool, WorldJournal

AGENTS_NAME = "agents.catalog"
WORLD_JOURNAL_NAME = "world.journal"
EXTERNAL_TOOLS_NAME = "tools.external"

TOOLS = InstanceKey[ToolRegistry]("tools.registry")


def construct(context: CompositionContext) -> None:
    """组成框架内建工具与外部注入工具的唯一目录。"""
    journal = cast("WorldJournal", context.require_name(WORLD_JOURNAL_NAME))
    agents = cast("AgentCatalog", context.require_name(AGENTS_NAME))
    external = context.require_name(EXTERNAL_TOOLS_NAME) if context.contains_name(EXTERNAL_TOOLS_NAME) else ()
    tools = ToolRegistry((*builtin_tools(agents=agents, journal=journal), *cast("tuple[Tool, ...]", external)))
    context.provide(TOOLS, tools)


PACKAGE_SPEC = PackageSpec(
    key=TOOLS,
    provides=(TOOLS,),
    requires=(WORLD_JOURNAL_NAME, AGENTS_NAME),
    register=construct,
)
