"""``src.tools`` 的自描述模块。"""

from __future__ import annotations

from src.contracts import TOOL_CONTRIBUTIONS, ScopeCatalog
from src.contracts.pkgs.agents import AgentCatalog
from src.contracts.pkgs.tools import ToolRegistry as ToolRegistryPort
from src.contracts.pkgs.world import WorldJournal
from src.kernel import ModuleContext, module
from src.tools import ToolRegistry
from src.tools.builtin import builtin_tools


@module(
    name="tools",
    provides=ToolRegistryPort,
    requires=(WorldJournal, AgentCatalog),
    consumes=(TOOL_CONTRIBUTIONS,),
    declares=(TOOL_CONTRIBUTIONS,),
)
def build(context: ModuleContext) -> ToolRegistryPort:
    journal = context.get(WorldJournal)
    agents = context.get(AgentCatalog)
    external = context.contributions(TOOL_CONTRIBUTIONS)
    scopes = context.settings.resolve(ScopeCatalog)
    return ToolRegistry((*builtin_tools(agents=agents, journal=journal, scopes=scopes), *external))


MODULE = build
