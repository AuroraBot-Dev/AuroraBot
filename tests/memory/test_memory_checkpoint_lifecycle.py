"""真实模组生命周期持久化并恢复配置所选 TGN 的动态图状态。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.memory_model import CONFIG_SPEC as MEMORY_MODEL_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurorabot.contracts import WorldFrontier
from aurorabot.contracts.memory import MemoryRequest
from aurorabot.contracts.pkgs.artifacts import ArtifactStore
from aurorabot.contracts.pkgs.memory import MemoryCheckpoints, MemoryReader
from aurorabot.contracts.resource_query import ResourceQuery
from aurorabot.mcp.config import PlatformsConfig
from aurorabot.memory_model.config import MemoryModelConfig
from aurorabot.memory_model.tgn import TemporalMemoryNetwork
from aurorabot.memory_model.training import train
from aurorabot.runtime import compose_runtime
from tests.memory.support import episodes
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path

    from aurora import AuroraConfig
    from aurorabot.contracts.artifact import ArtifactInfo
    from aurorabot.contracts.memory_graph import MemoryInteraction
    from aurorabot.memory_model.state import GraphState
    from aurorabot.runtime.core import AuroraRuntime


def _config(project: Path, *, interval: float = 3600.0, learned: bool = True) -> AuroraConfig:
    """模型使用真实训练权重，外部连接和主动节律明确关闭。"""
    config = load_config(project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    if learned:
        result = train(episodes("training"), episodes("validation", days=1), hidden_size=4, epochs=2)
        result.save(project / "memory.pt")
        config = config.with_value(
            MEMORY_MODEL_CONFIG, MemoryModelConfig("aurora:memory/model/tgn", "memory.pt", interval)
        )
    return config


async def _observe(runtime: AuroraRuntime) -> None:
    """通过真实世界端口产生可被记忆推荐的经历。"""
    await runtime.world.append_commit(
        commit_id="experiment-evidence",
        kind="observation",
        source="test",
        summary="实验已经完成，结果需要继续核对。",
        scopes=frozenset({"lab:world"}),
        based_on=WorldFrontier(),
        data={"result": "complete"},
    )
    snapshot = await runtime.assembly.get(MemoryReader).recall(MemoryRequest(query="实验结果"))
    assert snapshot.bundles


def test_shutdown_saves_and_startup_restores_without_replaying_or_reingesting_checkpoints(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关闭保存、重新装配恢复与默认召回隔离在同一真实运行路径上成立。"""
    config = _config(configured_project)

    async def scenario() -> None:
        runtime, lifecycle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        stop = asyncio.Event()
        try:
            await lifecycle.activate(stop)
            assert not await runtime.assembly.get(MemoryCheckpoints).initialize()
            await _observe(runtime)
        finally:
            stop.set()
            await lifecycle.close()
        resumed, handle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        stop = asyncio.Event()
        try:
            await handle.activate(stop)
            checkpoints = resumed.assembly.get(MemoryCheckpoints)
            assert await checkpoints.initialize()
            records = [
                item for item in (await resumed.world.stream(0, 100)).commits if item.kind == "memory.model.checkpoint"
            ]
            assert len(records) == 1

            def unexpected_update(self: TemporalMemoryNetwork, state: GraphState, event: MemoryInteraction) -> None:
                """实际历史与保存前相同，恢复后不应重新投影节点。"""
                raise AssertionError("不应重新计算已保存的图前缀")

            monkeypatch.setattr(TemporalMemoryNetwork, "update", unexpected_update)
            snapshot = await resumed.assembly.get(MemoryReader).recall(MemoryRequest(query="实验结果"))
            assert snapshot.recall is not None
            assert {item.memory_id for item in snapshot.recall.ranking} == {"experiment-evidence"}
            assert not set(records[0].scopes).intersection(snapshot.recall.candidate_scopes or ())
            assert await checkpoints.save() is None
        finally:
            stop.set()
            await handle.close()

    asyncio.run(scenario())


def test_periodic_module_task_saves_before_shutdown(configured_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """不依赖关闭钩子，也不需要模型推理再次运行即可保存已有动态图。"""
    config = _config(configured_project, interval=0.001)

    async def scenario() -> None:
        runtime, lifecycle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        stop = asyncio.Event()
        persisted = asyncio.Event()
        checkpoints = runtime.assembly.get(MemoryCheckpoints)
        actual_save = checkpoints.save

        async def save() -> ArtifactInfo | None:
            """观察真实资源和世界引用完成，不替换存储行为。"""
            info = await actual_save()
            if info is not None:
                persisted.set()
            return info

        monkeypatch.setattr(checkpoints, "save", save)
        try:
            await lifecycle.activate(stop)
            await _observe(runtime)
            await asyncio.wait_for(persisted.wait(), timeout=5)
            records = await runtime.world.stream(0, 100)
            assert any(item.kind == "memory.model.checkpoint" for item in records.commits)
        finally:
            stop.set()
            await lifecycle.close()

    asyncio.run(scenario())


def test_rule_policy_lifecycle_does_not_create_model_state_resources(configured_project: Path) -> None:
    """没有动态图的策略保持低成本，生命周期不制造空检查点。"""
    config = _config(configured_project, learned=False)

    async def scenario() -> None:
        runtime, lifecycle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        stop = asyncio.Event()
        try:
            await lifecycle.activate(stop)
            checkpoints = runtime.assembly.get(MemoryCheckpoints)
            assert not await checkpoints.initialize()
            await _observe(runtime)
            assert await checkpoints.save() is None
        finally:
            stop.set()
            await lifecycle.close()
        assert not (await runtime.assembly.get(ArtifactStore).find(ResourceQuery(domain="memory"))).items

    asyncio.run(scenario())


@pytest.mark.parametrize("interval", [0.0, -1.0, float("nan"), float("inf"), False])
def test_model_checkpoint_interval_requires_a_finite_positive_number(interval: float) -> None:
    """配置不能让保存任务进入无效或持续忙等的调度。"""
    with pytest.raises(ValueError, match="有限正数"):
        MemoryModelConfig(checkpoint_seconds=interval)
