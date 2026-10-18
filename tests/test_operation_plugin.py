"""独立插件通过声明增加领域操作、资源和模型工具。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from test_assembly import FakeModel

from aurora import load_config
from src.contracts import ToolCall, ToolOutput
from src.contracts.pkgs.resources import ResourceCatalog
from src.contracts.pkgs.tools import ToolRegistry
from src.contracts.resource import ResourceKey, ResourceRef
from src.runtime import assemble_runtime

if TYPE_CHECKING:
    from pathlib import Path

_PLUGIN = '''"""独立的示例领域模组。"""

from src.contracts import ToolScopes
from src.contracts.operation import OPERATION_CONTRIBUTIONS, OperationDefinition, OperationResult
from src.contracts.resource import (
    RESOURCE_ALIASES, RESOURCE_CONTRIBUTIONS, ResourceAlias, ResourceDescriptor, ResourceKey, ResourceRef,
)
from src.kernel import module


class Echo:
    """只通过契约定义和实现自己的查询。"""

    definition = OperationDefinition(
        ResourceRef(ResourceKey.parse("lab:example/query/echo"), "1"),
        "回显扩展输入",
        {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        "lab:tool/echo",
    )

    def scopes_for(self, request):
        """本查询没有附加业务世界域。"""
        return ToolScopes()

    async def execute(self, request):
        """返回结构化值，工具和终端由框架适配。"""
        return OperationResult({"value": request.arguments["value"]})


@module(name="lab_example", contributes=(OPERATION_CONTRIBUTIONS, RESOURCE_CONTRIBUTIONS, RESOURCE_ALIASES))
def build(context):
    """声明自己的资源与处理者，不修改内核或内建模块。"""
    context.contribute(OPERATION_CONTRIBUTIONS, Echo())
    ref = ResourceRef(ResourceKey.parse("lab:notes/document/guide"), "1")
    context.contribute(RESOURCE_CONTRIBUTIONS, ResourceDescriptor(ref, "扩展说明", metadata={"content": "示例"}))
    context.contribute(RESOURCE_ALIASES, ResourceAlias(ResourceKey.parse("lab:notes/document/default"), ref))


MODULE = build
'''


def test_plugin_declaration_adds_resource_command_and_tool_without_host_edits(configured_project: Path) -> None:
    """插件发现、依赖装配、资源别名和两种调用入口共同生效。"""
    directory = configured_project / "extensions" / "plugins"
    directory.mkdir(parents=True)
    (directory / "example.py").write_text(_PLUGIN, encoding="utf-8")

    async def scenario() -> None:
        model = FakeModel()
        runtime = assemble_runtime(load_config(configured_project), model, output=lambda _: None)
        try:
            resources = runtime.assembly.get(ResourceCatalog)
            alias = resources.resolve(ResourceRef(ResourceKey.parse("lab:notes/document/default")))
            assert alias.metadata["content"] == "示例"
            response = await runtime.terminal.dispatch_terminal('/call lab:example/query/echo {"value":"好"}')
            assert not response.is_error
            assert json.loads(response.text or "{}")["data"] == {"value": "好"}
            tools = runtime.assembly.get(ToolRegistry)
            result = await tools.execute(ToolCall("echo", "lab:tool/echo", {"value": "好"}))
            assert isinstance(result, ToolOutput) and not result.is_error
            assert json.loads(result.content) == {"value": "好"}
            assert model.requests == []
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
