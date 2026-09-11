"""``src.tools`` 的自描述模块。"""

from __future__ import annotations

from src.contracts import TOOL_CONTRIBUTIONS, AgentCatalog, WorldJournal
from src.contracts import ToolRegistry as ToolRegistryPort
from src.kernel import ModuleContext, module
from src.tools import ToolRegistry
from src.tools.builtin import builtin_tools


@module(
    name="tools",
    provides=ToolRegistryPort,
    requires=(WorldJournal, AgentCatalog),
    consumes=(TOOL_CONTRIBUTIONS,),
)
def build(context: ModuleContext) -> ToolRegistryPort:
    journal = context.get(WorldJournal)
    agents = context.get(AgentCatalog)
    external = context.contributions(TOOL_CONTRIBUTIONS)
    return ToolRegistry((*builtin_tools(agents=agents, journal=journal), *external))


MODULE = build
