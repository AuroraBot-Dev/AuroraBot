"""``src.agents`` 的自描述模块。"""

from __future__ import annotations

from src.agents.catalog import AgentCatalog
from src.agents.config import AgentsConfig
from src.contracts import (
    BUILTIN_TOOL_NAMES,
    TOOL_CONTRIBUTIONS,
    AgentDefinition,
    TagsConfig,
)
from src.contracts.agent_resource import AGENT_MEDIA_TYPE
from src.contracts.pkgs.agents import AgentCatalog as AgentCatalogPort
from src.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from src.kernel import ModuleContext, module
from src.utils import resolve_names


@module(
    name="agents",
    provides=AgentCatalogPort,
    requires=AgentCatalogPort,
    contributes=RESOURCE_CONTENTS,
    consumes=TOOL_CONTRIBUTIONS,
)
def build(context: ModuleContext) -> AgentCatalogPort:
    """读取实际选中目录，正文归档不反向参与工具和资源目录的构造。"""
    catalog = context.get_optional(AgentCatalogPort)
    if catalog is None:
        external = context.contributions(TOOL_CONTRIBUTIONS)
        available = BUILTIN_TOOL_NAMES | frozenset(tool.definition.name for tool in external)
        tags = context.settings.resolve(TagsConfig).table
        catalog = AgentCatalog(
            AgentDefinition(
                item.id,
                item.description,
                item.prompt,
                item.model,
                resolve_names(available, tags.expand(item.tools, label=item.id), label=item.id),
                item.children,
            )
            for item in context.settings.resolve(AgentsConfig).agents
        )
    for definition in catalog.definitions:
        context.contribute(RESOURCE_CONTENTS, ResourceContent(definition.ref, definition.content, AGENT_MEDIA_TYPE))
    return catalog


MODULE = build
