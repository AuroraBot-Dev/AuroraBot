"""真实模型输入、工具执行事实与可读取接口正文共用确定版本。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurora.configs.agents import CONFIG_SPEC as AGENTS_CONFIG
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurorabot.agents.config import AgentsConfig
from aurorabot.contracts import ChatMessage, ToolCall, ToolOutput, TreeStatus
from aurorabot.contracts.operation import OperationKind, OperationRequest, OperationStatus
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.contracts.pkgs.tools import ToolRegistry
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.contracts.tool import WAIT_TOOL
from aurorabot.mcp.config import PlatformsConfig
from aurorabot.runtime import compose_runtime
from tests.model_support import ScriptedModel as FakeModel
from tests.test_tools import EchoTool

if TYPE_CHECKING:
    from pathlib import Path

    from aurora import AuroraConfig


def _config(project: Path) -> AuroraConfig:
    """关闭外部连接和自动认知，只让测试发起的认知推动世界。"""
    config = load_config(project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    return config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )


def test_visible_tool_versions_match_requests_execution_facts_and_public_content(configured_project: Path) -> None:
    """实际可见接口进入模型来源，执行后可以从世界引用读回对应正文。"""
    tool = EchoTool()
    expected = tool.definition
    config = _config(configured_project)
    config = config.with_value(
        AGENTS_CONFIG,
        AgentsConfig(
            tuple(
                replace(item, tools=(*item.tools, expected.name)) if item.id == "aurora:agent/definition/root" else item
                for item in config.get(AGENTS_CONFIG).agents
            )
        ),
    )
    call = ToolCall("echo", expected.name, {"value": "核对完成"})
    model = FakeModel([ChatMessage.assistant(tool_calls=(call,)), ChatMessage.assistant("已确认")])

    async def scenario() -> None:
        """经正式装配执行工具，再通过相同操作路由读取接口。"""
        runtime, lifecycle = await compose_runtime(config, model, (tool,), output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            tree = await runtime.run("核对结果", tree_id="tool-version")
            assert tree.status is TreeStatus.COMPLETED
            registry = runtime.assembly.get(ToolRegistry)
            hidden = next(item for item in registry.definitions if item.name == WAIT_TOOL)
            for index, request in enumerate(model.requests):
                assert expected.ref in request.resources
                assert hidden.ref not in request.resources
                assert all(item.ref in request.resources for item in request.tools)
                fact = await runtime.world.commit(f"tool-version:{tree.root_id}:model:{index}:requested")
                assert fact is not None
                assert list(fact.data["tool_refs"]) == [
                    {"key": item.name, "revision": item.ref.revision} for item in request.tools
                ]
            requested = await runtime.world.commit(f"tool-version:{tree.root_id}:echo:requested")
            result = await runtime.world.commit(f"tool-version:{tree.root_id}:echo:result")
            assert requested is not None and result is not None
            assert requested.data["tool_ref"] == {"key": expected.name, "revision": expected.ref.revision}
            assert result.data["tool_ref"] == requested.data["tool_ref"]
            read = OperationRequest(
                "read-executed-tool-interface",
                "aurora:bot/default",
                "test",
                ResourceRef(ResourceKey.parse("aurora:artifacts/query/read"), "1"),
                OperationKind.QUERY,
                {**result.data["tool_ref"], "encoding": "utf-8", "limit": 16384},
            )
            content = await runtime.assembly.get(OperationRegistry).dispatch(read)
            assert content.status is OperationStatus.SUCCEEDED
            assert content.data["text"].encode("utf-8") == expected.content
        finally:
            await lifecycle.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("registered", [False, True])
def test_rejected_calls_do_not_invent_a_visible_interface_version(
    configured_project: Path, *, registered: bool
) -> None:
    """已注册但不可见的工具与未知工具都不执行，也不能借目录内容伪造来源。"""
    invoked: list[ToolCall] = []

    class HiddenTool(EchoTool):
        """观察底层是否被调用，保留真实工具接口。"""

        async def execute(self, call: ToolCall) -> ToolOutput:
            """调用意味着可见性检查失守。"""
            invoked.append(call)
            return await super().execute(call)

    tool = HiddenTool()
    name = tool.definition.name if registered else "test:tool/definition/missing"
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(ToolCall("hidden", name, {"value": "拒绝"}),)),
            ChatMessage.assistant("已知悉"),
        ]
    )

    async def scenario() -> None:
        """检查实际世界事实，空引用不能被当作某个可用版本。"""
        runtime, lifecycle = await compose_runtime(_config(configured_project), model, (tool,), output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            tree = await runtime.run("检查调用边界", tree_id="hidden-tool")
            for stage in ("requested", "result"):
                fact = await runtime.world.commit(f"hidden-tool:{tree.root_id}:hidden:{stage}")
                assert fact is not None
                assert fact.data["tool"] == name
                assert fact.data["tool_ref"] is None
            assert not invoked
            assert all(tool.definition.ref not in request.resources for request in model.requests)
        finally:
            await lifecycle.close()

    asyncio.run(scenario())
