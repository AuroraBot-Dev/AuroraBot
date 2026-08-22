"""构造并导出预定义 AgentDefinition 目录。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.configuration.agents import AGENTS_CONFIG
from src.agents import AgentCatalog
from src.contracts import AgentDefinition

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

AGENTS = InstanceKey[AgentCatalog]("agents.catalog")


def register(context: CompositionContext) -> None:
    configuration = context.config.get(AGENTS_CONFIG)
    context.provide(
        AGENTS,
        AgentCatalog(
            AgentDefinition(
                item.definition_id,
                item.description,
                item.prompt,
                item.model,
                item.tools,
                item.children,
            )
            for item in configuration.definitions
        ),
    )
