"""构造并导出预定义 AgentDefinition 目录。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.configuration.agents import AGENTS_CONFIG
from src.agents import AgentCatalog
from src.contracts import AgentDefinition
from src.tools.builtin import DELEGATE_TOOL, WAIT_TOOL, WORLD_READ_TOOL, WORLD_TREES_TOOL
from src.utils import resolve_names

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

AGENTS = InstanceKey[AgentCatalog]("agents.catalog")

_BUILTIN_NAMES = frozenset({DELEGATE_TOOL, WAIT_TOOL, WORLD_READ_TOOL, WORLD_TREES_TOOL})


def register(context: CompositionContext) -> None:
    configuration = context.config.get(AGENTS_CONFIG)
    available = _BUILTIN_NAMES | frozenset(tool.definition.name for tool in context.tools)
    context.provide(
        AGENTS,
        AgentCatalog(
            AgentDefinition(
                item.definition_id,
                item.description,
                item.prompt,
                item.model,
                resolve_names(available, item.tools, label=item.definition_id),
                item.children,
            )
            for item in configuration.definitions
        ),
    )
