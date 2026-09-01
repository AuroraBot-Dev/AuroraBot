"""构造并导出 ``src.tools`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.composer import InstanceKey, ModuleSpec
from aurora.composition.agents import AGENTS, EXTERNAL_TOOLS
from aurora.composition.world import WORLD_JOURNAL
from aurora.views import tool_dict
from src.tools import ToolRegistry
from src.tools.builtin import builtin_tools

if TYPE_CHECKING:
    from aurora.composer import CompositionContext


class ToolsOps:
    """ToolRegistry 的窄 ops 端口适配器。"""

    def __init__(self, tools: ToolRegistry) -> None:
        self._tools = tools

    def tool_catalog(self) -> dict[str, Any]:
        return {"tools": [tool_dict(definition) for definition in self._tools.definitions]}

    def tool_detail(self, tool_id: str) -> dict[str, Any] | None:
        definition = next((item for item in self._tools.definitions if item.name == tool_id), None)
        return tool_dict(definition) if definition is not None else None


TOOLS = InstanceKey[ToolRegistry]("tools.registry")
TOOLS_OPS = InstanceKey[ToolsOps]("tools.ops")


def _register(context: CompositionContext) -> None:
    """组成框架内建工具与外部注入工具的唯一目录。"""
    journal = context.require(WORLD_JOURNAL)
    agents = context.require(AGENTS)
    external = context.require(EXTERNAL_TOOLS) if context.contains(EXTERNAL_TOOLS) else ()
    tools = ToolRegistry((*builtin_tools(agents=agents, journal=journal), *external))
    context.provide(TOOLS, tools)
    context.provide(TOOLS_OPS, ToolsOps(tools))


MODULE_SPEC = ModuleSpec(key=TOOLS, requires=(WORLD_JOURNAL, AGENTS), register=_register)
