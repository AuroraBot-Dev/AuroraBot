"""``src.agents`` 的自描述模块。"""

from __future__ import annotations

from src.agents import AgentCatalog
from src.agents.config import AgentsConfig
from src.contracts import (
    BUILTIN_TOOL_NAMES,
    TOOL_CONTRIBUTIONS,
    AgentDefinition,
)
from src.contracts import (
    AgentCatalog as AgentCatalogPort,
)
from src.kernel import ModuleContext, module
from src.utils import resolve_names


@module(name="agents", provides=AgentCatalogPort, consumes=(TOOL_CONTRIBUTIONS,))
def build(context: ModuleContext) -> AgentCatalogPort:
    external = context.contributions(TOOL_CONTRIBUTIONS)
    available = BUILTIN_TOOL_NAMES | frozenset(tool.definition.name for tool in external)
    return AgentCatalog(
        AgentDefinition(
            item.id,
            item.description,
            item.prompt,
            item.model,
            resolve_names(available, item.tools, label=item.id),
            item.children,
        )
        for item in context.settings.get(AgentsConfig).agents
    )


MODULE = build
