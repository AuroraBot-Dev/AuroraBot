"""持久运行实例身份不能因重启或重新创建运行器而被再次执行。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from test_assembly import FakeModel
from test_engine_runtime import FakeModel as SequenceModel
from test_engine_runtime import _agent, _runner

from aurora import load_config
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from src.contracts import AgentTree, ChatMessage, TreeLaunchRequest
from src.mcp.config import PlatformsConfig
from src.runtime import compose_runtime
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("entry", ["run", "launch"])
def test_restart_rejects_an_existing_instance_before_new_facts_or_model_calls(
    configured_project: Path, entry: str
) -> None:
    """普通输入和主动唤起都在执行前核对世界事实，不能把旧 ID 当成新实例。"""
    config = load_config(configured_project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )

    async def scenario() -> None:
        """关闭并重建实际世界连接，以游标不变证明拒绝前没有追加新事实。"""
        runtime, lifecycle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        stop = asyncio.Event()
        stop.set()
        try:
            await lifecycle.activate(stop)
            await runtime.launch_tree(TreeLaunchRequest("核对结果", tree_id="persistent-instance"))
        finally:
            await lifecycle.close()
        model = FakeModel()
        resumed, handle = await compose_runtime(config, model, output=lambda _: None)
        try:
            await handle.activate(stop)
            before = await resumed.world.cursor()
            with pytest.raises(ValueError, match="AgentTree 已存在"):
                if entry == "run":
                    await resumed.run("核对结果", tree_id="persistent-instance")
                else:
                    await resumed.launch_tree(TreeLaunchRequest("核对结果", tree_id="persistent-instance"))
            assert await resumed.world.cursor() == before
            assert not model.requests
        finally:
            await handle.close()

    asyncio.run(scenario())


def test_new_runner_cannot_reexecute_a_recorded_instance(tmp_path: Path) -> None:
    """绕过进程门面直接使用引擎端口时，同一身份也不能再次触发推理。"""

    async def scenario() -> None:
        """保留同一个持久世界，更换运行器与模型实例。"""
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        root = _agent()
        tree = AgentTree.create("persistent-instance", "root", root, "核对结果")
        try:
            first = SequenceModel([ChatMessage.assistant("已完成")])
            await _runner(first, (root,), world=world).run(tree)
            second = SequenceModel([ChatMessage.assistant("不能再次执行")])
            before = await world.cursor()
            with pytest.raises(ValueError, match="AgentTree 已存在"):
                await _runner(second, (root,), world=world).run(tree)
            assert not second.requests
            assert await world.cursor() == before
        finally:
            await world.close()

    asyncio.run(scenario())
