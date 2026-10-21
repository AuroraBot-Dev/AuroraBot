"""真实父子认知的节点快照、模型输入与世界事实共用原型版本。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from aurora_bot.contracts import ChatMessage, ToolCall
from aurora_bot.contracts.pkgs.agents import AgentCatalog
from aurora_bot.contracts.tool import DELEGATE_TOOL
from aurora_bot.mcp.config import PlatformsConfig
from aurora_bot.runtime import compose_runtime
from aurora_cli import load_config
from aurora_cli.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora_cli.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from tests.support.model import ScriptedModel as FakeModel

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
            tree = await runtime.run("委派核对并整合结果", run_id="agent-provenance")
            assert tree.status == "completed"
            catalog = runtime.assembly.get(AgentCatalog)
            root = catalog.get(runtime.root.agent)
            child = catalog.get(worker_id)
            assert root.ref != child.ref
            child_id = f"{tree.run_id}:1"
            steps = (
                (root, runtime.root.node_id, 0),
                (child, child_id, 0),
                (root, runtime.root.node_id, 1),
            )
            for request, (node, node_id, index) in zip(model.requests, steps, strict=True):
                expected = {"key": node.definition_id, "revision": node.ref.revision}
                assert request.resources[0] == node.ref
                assert request.resources.count(node.ref) == 1
                record = await runtime.world.commit(f"{tree.run_id}:{node_id}:model:{index}:requested")
                assert record is not None
                assert record.data["definition_ref"] == expected
                assert list(record.data["resources"]) == [
                    {"key": str(ref.key), "revision": ref.revision} for ref in request.resources
                ]
            started = await runtime.world.commit(f"{tree.run_id}:tree:started")
            spawned = await runtime.world.commit(f"{tree.run_id}:{child_id}:spawned")
            assert started is not None and spawned is not None
            assert started.data["definition_ref"] == {
                "key": root.definition_id,
                "revision": root.ref.revision,
            }
            assert spawned.data["definition_ref"] == {
                "key": child.definition_id,
                "revision": child.ref.revision,
            }
            delegate = next(tool for tool in model.requests[0].tools if tool.name == DELEGATE_TOOL)
            result = await runtime.world.commit(f"{tree.run_id}:{runtime.root.node_id}:delegate:result")
            assert result is not None
            assert result.data["tool_ref"] == {"key": DELEGATE_TOOL, "revision": delegate.ref.revision}
        finally:
            await lifecycle.close()

    asyncio.run(scenario())
