"""认知过程定义驱动真实上界，运行实例从开始事实绑定其确定版本。"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from test_assembly import FakeModel
from test_engine_runtime import FakeModel as SequenceModel
from test_engine_runtime import _agent, _assembler

from aurora import load_config
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.engine import CONFIG_SPEC as ENGINE_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurorabot.agents import AgentCatalog
from aurorabot.contracts import AgentTree, ChatMessage, ToolCall, TreeStatus
from aurorabot.contracts.operation import OperationKind, OperationRequest, OperationStatus
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.contracts.process import TreeProcessDefinition
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.engine import AgentTreeRunner
from aurorabot.engine.config import EngineConfig
from aurorabot.mcp.config import PlatformsConfig
from aurorabot.runtime import compose_runtime
from aurorabot.tools import DELEGATE_TOOL, DelegateTool, ToolRegistry

if TYPE_CHECKING:
    from pathlib import Path


def test_process_version_covers_every_execution_setting() -> None:
    """身份、策略和每项上界都属于执行定义，同名更改不能沿用旧版本。"""
    original = TreeProcessDefinition()
    assert original.ref.revision == hashlib.sha256(original.content).hexdigest()
    for changed in (
        replace(original, max_depth=1),
        replace(original, max_nodes=1),
        replace(original, max_steps=1),
        replace(original, strategy="breadth_first"),
        replace(original, key=ResourceKey.parse("lab:engine/process/bounded")),
    ):
        assert changed.ref != original.ref


@pytest.mark.parametrize("limit", [0, -1, True])
def test_process_limits_are_positive_integers(limit: int) -> None:
    """布尔值也不能作为执行次数发布。"""
    with pytest.raises(ValueError, match="运行上界"):
        TreeProcessDefinition(max_steps=limit)


def test_runner_cannot_label_its_loop_as_an_unimplemented_strategy() -> None:
    """过程声明必须与执行方式一致，不支持的策略在运行开始前拒绝。"""
    root = _agent()
    with pytest.raises(ValueError, match="不支持认知策略"):
        AgentTreeRunner(
            SequenceModel([]),
            _assembler(),
            AgentCatalog((root,)),
            ToolRegistry(),
            process=TreeProcessDefinition(strategy="breadth_first"),
        )


@pytest.mark.parametrize("field", ["max_depth", "max_nodes"])
def test_delegation_limits_come_from_the_published_process(field: str) -> None:
    """修改过程定义会实际限制委派，不能只改变资源说明。"""
    process = replace(TreeProcessDefinition(), **{field: 1})
    root = _agent(tools=frozenset({DELEGATE_TOOL}), children=frozenset({"worker"}))
    worker = _agent("worker", "worker", tools=frozenset({DELEGATE_TOOL}), children=frozenset({"worker"}))
    call = ToolCall("delegate", DELEGATE_TOOL, {"agent": worker.definition_id, "instruction": "检查证据"})
    responses = [ChatMessage.assistant(tool_calls=(call,))]
    if field == "max_depth":
        responses.extend((ChatMessage.assistant(tool_calls=(call,)), ChatMessage.assistant("子节点完成")))
    responses.append(ChatMessage.assistant("父节点完成"))
    model = SequenceModel(responses)
    agents = AgentCatalog((root, worker))
    runner = AgentTreeRunner(model, _assembler(), agents, ToolRegistry((DelegateTool(agents),)), process=process)
    result = asyncio.run(runner.run(AgentTree.create("tree", "root", root, "开始核对")))
    assert result.status is TreeStatus.COMPLETED
    assert runner.process_definition is process
    boundary = "深度上限" if field == "max_depth" else "节点数上限"
    assert any(boundary in message.content for node in result.nodes for message in node.messages if message.is_error)


def test_instance_keeps_original_process_after_config_change_and_restart(configured_project: Path) -> None:
    """实例保留原始身份与 Bot 归属，历史定义从世界引用经正式入口读取。"""
    config = load_config(configured_project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    config = config.with_value(ENGINE_CONFIG, EngineConfig(2, 3, 1))

    async def scenario() -> None:
        """重新装配产生新过程版本，但不能改写旧运行实例的执行依据。"""
        runtime, lifecycle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        original = runtime.runner.process_definition
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            tree = await runtime.run("读取运行依据", tree_id="process:tree")
            assert tree.status is TreeStatus.COMPLETED
        finally:
            await lifecycle.close()
        revised = config.with_value(ENGINE_CONFIG, EngineConfig(2, 3, 2))
        resumed, handle = await compose_runtime(revised, FakeModel(), output=lambda _: None)
        try:
            await handle.activate(stop)
            assert resumed.runner.process_definition.ref != original.ref
            started = await resumed.world.commit("process:tree:tree:started")
            assert started is not None
            assert started.data["process_ref"] == {"key": str(original.key), "revision": original.ref.revision}
            assert started.data["instance"] == {
                "instance_id": "process:tree",
                "bot_id": "aurora:bot/default",
                "definition": started.data["process_ref"],
            }
            request = OperationRequest(
                "read-original-process",
                "aurora:bot/default",
                "test",
                ResourceRef(ResourceKey.parse("aurora:artifacts/query/read"), "1"),
                OperationKind.QUERY,
                {**started.data["instance"]["definition"], "encoding": "utf-8", "limit": 16384},
            )
            result = await resumed.assembly.get(OperationRegistry).dispatch(request)
            assert result.status is OperationStatus.SUCCEEDED
            assert result.data["text"].encode("utf-8") == original.content
        finally:
            await handle.close()

    asyncio.run(scenario())
