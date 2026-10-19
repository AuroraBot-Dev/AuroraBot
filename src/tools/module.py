"""``src.tools`` 的自描述模块。"""

from __future__ import annotations

from src.contracts import TOOL_CONTRIBUTIONS, ScopeCatalog
from src.contracts.pkgs.agents import AgentCatalog
from src.contracts.pkgs.tools import ToolRegistry as ToolRegistryPort
from src.contracts.pkgs.world import WorldReader
from src.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from src.contracts.tool_resource import TOOL_MEDIA_TYPE
from src.kernel import ModuleContext, module
from src.tools import ToolRegistry
from src.tools.builtin import builtin_tools


@module(
    name="tools",
    provides=ToolRegistryPort,
    requires=(ToolRegistryPort, WorldReader, AgentCatalog, ScopeCatalog),
    consumes=(TOOL_CONTRIBUTIONS,),
    declares=(TOOL_CONTRIBUTIONS,),
    contributes=RESOURCE_CONTENTS,
)
def build(context: ModuleContext) -> ToolRegistryPort:
    """归档实际选中目录的接口，不用失选实现重新构造另一套工具。"""
    registry = context.get_optional(ToolRegistryPort)
    if registry is None:
        registry = _registry(context)
    for definition in registry.definitions:
        context.contribute(RESOURCE_CONTENTS, ResourceContent(definition.ref, definition.content, TOOL_MEDIA_TYPE))
    return registry


def _registry(context: ModuleContext) -> ToolRegistryPort:
    """内建工具和扩展贡献只在默认目录被采用时绑定。"""
    journal = context.get(WorldReader)
    agents = context.get(AgentCatalog)
    external = context.contributions(TOOL_CONTRIBUTIONS)
    scopes = context.get(ScopeCatalog)
    return ToolRegistry((*builtin_tools(agents=agents, journal=journal, scopes=scopes), *external))


MODULE = build
