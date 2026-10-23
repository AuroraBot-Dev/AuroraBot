"""``aurora_bot.tools`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.contracts import TOOL_CONTRIBUTIONS
from aurora_bot.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from aurora_bot.contracts.tool_resource import TOOL_MEDIA_TYPE
from aurora_bot.kernel import ModuleContext, module
from aurora_bot.kernel.hooks import service_namespace
from aurora_bot.tools.builtin import builtin_tools
from aurora_bot.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.tools import ToolRegistry as ToolRegistryPort

CALLS = service_namespace(
    "tools",
    "tools",
    methods=("definitions_for", "scopes_for"),
    asynchronous=("execute",),
    attributes=("definitions", "names"),
)


@module(
    name="tools",
    provides="tools",
    requires=("tools", "world.reader", "agents", "scopes"),
    contributes=RESOURCE_CONTENTS,
    consumes=TOOL_CONTRIBUTIONS,
    declares=TOOL_CONTRIBUTIONS,
    points=CALLS.spec.points,
    handlers=CALLS.spec.handlers,
)
def build(context: ModuleContext) -> ToolRegistryPort:
    """归档实际选中目录的接口，不用失选实现重新构造另一套工具。"""
    registry = context.get_optional("tools")
    if registry is None:
        journal = context.get("world.reader")
        external = context.contributions(TOOL_CONTRIBUTIONS)
        scopes = context.get("scopes")
        registry = ToolRegistry((*builtin_tools(journal=journal, scopes=scopes), *external))
    for definition in registry.definitions:
        context.contribute(RESOURCE_CONTENTS, ResourceContent(definition.ref, definition.content, TOOL_MEDIA_TYPE))
    return registry


MODULE = build
