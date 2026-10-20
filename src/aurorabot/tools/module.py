"""``aurorabot.tools`` 的自描述模块。"""

from __future__ import annotations

from aurorabot.contracts import TOOL_CONTRIBUTIONS, ScopeCatalog
from aurorabot.contracts.pkgs.agents import AgentCatalog
from aurorabot.contracts.pkgs.tools import ToolRegistry as ToolRegistryPort
from aurorabot.contracts.pkgs.world import WorldReader
from aurorabot.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from aurorabot.contracts.tool_resource import TOOL_MEDIA_TYPE
from aurorabot.kernel import ModuleContext, module
from aurorabot.tools.builtin import builtin_tools
from aurorabot.tools.registry import ToolRegistry


@module(
    name="tools",
    provides=ToolRegistryPort,
    requires=(ToolRegistryPort, WorldReader, AgentCatalog, ScopeCatalog),
    contributes=RESOURCE_CONTENTS,
    consumes=TOOL_CONTRIBUTIONS,
    declares=TOOL_CONTRIBUTIONS,
)
def build(context: ModuleContext) -> ToolRegistryPort:
    """归档实际选中目录的接口，不用失选实现重新构造另一套工具。"""
    registry = context.get_optional(ToolRegistryPort)
    if registry is None:
        journal = context.get(WorldReader)
        agents = context.get(AgentCatalog)
        external = context.contributions(TOOL_CONTRIBUTIONS)
        scopes = context.get(ScopeCatalog)
        registry = ToolRegistry((*builtin_tools(agents=agents, journal=journal, scopes=scopes), *external))
    for definition in registry.definitions:
        context.contribute(RESOURCE_CONTENTS, ResourceContent(definition.ref, definition.content, TOOL_MEDIA_TYPE))
    return registry


MODULE = build
