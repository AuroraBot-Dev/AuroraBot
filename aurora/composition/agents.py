"""构造并导出 ``src.agents`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey, PackageSpec
from aurora.configuration.agents import AGENTS_CONFIG
from src.agents import AgentCatalog
from src.contracts import AgentDefinition, Tool
from src.tools.builtin import DELEGATE_TOOL, WAIT_TOOL, WORLD_READ_TOOL, WORLD_TREES_TOOL
from src.utils import resolve_names

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

_BUILTIN_NAMES = frozenset({DELEGATE_TOOL, WAIT_TOOL, WORLD_READ_TOOL, WORLD_TREES_TOOL})

AGENTS = InstanceKey[AgentCatalog]("agents.catalog")
EXTERNAL_TOOLS = InstanceKey[tuple[Tool, ...]]("tools.external")


def construct(context: CompositionContext) -> None:
    """构造并注册 ``src.agents`` 的项目实例。"""
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


PACKAGE_SPEC = PackageSpec(
    key=AGENTS,
    provides=(AGENTS,),
    requires=(),
    register=construct,
)
