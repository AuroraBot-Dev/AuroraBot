"""真实父子认知的节点快照、模型输入与世界事实共用原型版本。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from test_engine_runtime import FakeModel

from aurora import load_config
from aurora.configs.cadence import CADENCE_CONFIG
from aurora.configs.platforms import PLATFORMS_CONFIG
from src.contracts import ChatMessage, ToolCall, TreeStatus
from src.contracts.pkgs.agents import AgentCatalog
from src.contracts.tool import DELEGATE_TOOL
from src.mcp.config import PlatformsConfig
from src.runtime import compose_runtime

if TYPE_CHECKING:
    from pathlib import Path


def test_actual_delegation_records_each_node_definition_at_the_time_of_use(configured_project: Path) -> None:
    """父节点恢复后沿用自身版本，子节点的模型请求与创建事实使用子原型版本。"""
    config = load_config(configured_project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    worker_id = "aurora:agent/definition/fast-worker"
    call = ToolCall("delegate", DELEGATE_TOOL, {"agent": worker_id, "instruction": "核对实验记录"})
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(call,)),
            ChatMessage.assistant("记录核对完成"),
            ChatMessage.assistant("结果已整合"),
        ]
    )

    async def scenario() -> None:
        """运行正式装配的认知循环，检查实际发出的三次请求与持久化事件。"""
        runtime, lifecycle = await compose_runtime(config, model, output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            tree = await runtime.run("委派核对并整合结果", tree_id="agent-provenance")
            assert tree.status is TreeStatus.COMPLETED
            root, child = tree.nodes
            catalog = runtime.assembly.get(AgentCatalog)
            assert root.definition is catalog.get(root.definition_id)
            assert child.definition is catalog.get(worker_id)
            assert root.definition_ref != child.definition_ref
            steps = ((root, 0), (child, 0), (root, 1))
            for request, (node, index) in zip(model.requests, steps, strict=True):
                expected = {"key": node.definition_id, "revision": node.definition_ref.revision}
                assert request.resources[0] == node.definition_ref
                assert request.resources.count(node.definition_ref) == 1
                record = await runtime.world.commit(f"{tree.tree_id}:{node.node_id}:model:{index}:requested")
                assert record is not None
                assert record.data["definition_ref"] == expected
                assert list(record.data["resources"]) == [
                    {"key": str(ref.key), "revision": ref.revision} for ref in request.resources
                ]
            started = await runtime.world.commit(f"{tree.tree_id}:tree:started")
            spawned = await runtime.world.commit(f"{tree.tree_id}:{child.node_id}:spawned")
            assert started is not None and spawned is not None
            assert started.data["definition_ref"] == {
                "key": root.definition_id,
                "revision": root.definition_ref.revision,
            }
            assert spawned.data["definition_ref"] == {
                "key": child.definition_id,
                "revision": child.definition_ref.revision,
            }
            delegate = next(tool for tool in model.requests[0].tools if tool.name == DELEGATE_TOOL)
            result = await runtime.world.commit(f"{tree.tree_id}:{root.node_id}:delegate:result")
            assert result is not None
            assert result.data["tool_ref"] == {"key": DELEGATE_TOOL, "revision": delegate.ref.revision}
        finally:
            await lifecycle.close()

    asyncio.run(scenario())
