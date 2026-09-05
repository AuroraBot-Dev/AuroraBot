"""构造并导出预定义 AgentDefinition 目录与外部工具集合。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.composer import InstanceKey, ModuleSpec
from aurora.configuration.agents import AGENTS_CONFIG
from aurora.views import agent_dict
from src.agents import AgentCatalog
from src.contracts import AgentDefinition, Tool
from src.tools.builtin import DELEGATE_TOOL, WAIT_TOOL, WORLD_READ_TOOL, WORLD_TREES_TOOL
from src.utils import resolve_names

if TYPE_CHECKING:
    from aurora.composer import CompositionContext


class AgentOps:
    """AgentCatalog 的窄 ops 端口适配器。"""

    def __init__(self, agents: AgentCatalog) -> None:
        self._agents = agents

    def agent_catalog(self) -> dict[str, Any]:
        return {"agents": [agent_dict(definition) for definition in self._agents.definitions]}

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        try:
            definition = self._agents.get(agent_id)
        except ValueError:
            return None
        return agent_dict(definition)


AGENTS = InstanceKey[AgentCatalog]("agents.catalog")
AGENTS_OPS = InstanceKey[AgentOps]("agents.ops")
EXTERNAL_TOOLS = InstanceKey[tuple[Tool, ...]]("tools.external")

_BUILTIN_NAMES = frozenset({DELEGATE_TOOL, WAIT_TOOL, WORLD_READ_TOOL, WORLD_TREES_TOOL})


def _register(context: CompositionContext) -> None:
    external: tuple[Tool, ...] = context.require(EXTERNAL_TOOLS) if context.contains(EXTERNAL_TOOLS) else ()
    available = _BUILTIN_NAMES | frozenset(tool.definition.name for tool in external)
    agents = AgentCatalog(
        AgentDefinition(
            item.id,
            item.description,
            item.prompt,
            item.model,
            resolve_names(available, item.tools, label=item.id),
            item.children,
        )
        for item in context.config.get(AGENTS_CONFIG)
    )
    context.provide(AGENTS, agents)
    context.provide(AGENTS_OPS, AgentOps(agents))


MODULE_SPEC = ModuleSpec(key=AGENTS, requires=(), register=_register)
