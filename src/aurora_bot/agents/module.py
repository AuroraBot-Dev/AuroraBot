"""``aurora_bot.agents`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.agents.catalog import AgentCatalog
from aurora_bot.agents.config import AgentsConfig
from aurora_bot.contracts import (
    BUILTIN_TOOL_NAMES,
    TOOL_CONTRIBUTIONS,
    AgentDefinition,
    TagsConfig,
)
from aurora_bot.contracts.agent_resource import AGENT_MEDIA_TYPE
from aurora_bot.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from aurora_bot.kernel import ModuleContext, module
from aurora_bot.kernel.hooks import service_namespace
from aurora_bot.utils import resolve_names

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.agents import AgentCatalog as AgentCatalogPort

CALLS = service_namespace("agents", "agents", methods=("get",), attributes=("definitions", "ids"))


@module(
    name="agents",
    provides="agents",
    requires="agents",
    contributes=RESOURCE_CONTENTS,
    consumes=TOOL_CONTRIBUTIONS,
    points=CALLS.spec.points,
    handlers=CALLS.spec.handlers,
)
def build(context: ModuleContext) -> AgentCatalogPort:
    """读取实际选中目录，正文归档不反向参与工具和资源目录的构造。"""
    catalog = context.get_optional("agents")
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
            )
            for item in context.settings.resolve(AgentsConfig).agents
        )
    for definition in catalog.definitions:
        context.contribute(RESOURCE_CONTENTS, ResourceContent(definition.ref, definition.content, AGENT_MEDIA_TYPE))
    return catalog


MODULE = build
