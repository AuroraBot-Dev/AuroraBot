"""真实训练的两个模型共同参与主体生活，权重与连续性跨进程恢复。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from memory_support import episodes
from rhythm_support import make_episode
from test_assembly import FakeModel
from test_bot_lifecycle import PlanningModel

from aurora import load_config
from aurora.configs.cadence import CONFIG_SPEC as CADENCE_CONFIG
from aurora.configs.memory_model import CONFIG_SPEC as MEMORY_MODEL_CONFIG
from aurora.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG
from aurora.configs.rhythm import CONFIG_SPEC as RHYTHM_CONFIG
from src.cadence import Cadence
from src.cadence.state import observation_data
from src.clock import PersistentBotClock
from src.contracts import ScopeCatalog, WorldFrontier
from src.contracts.bot import WakeStatus
from src.contracts.pkgs.ai import Model
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.cadence import Cadence as CadencePort
from src.contracts.pkgs.cadence import RhythmPolicy
from src.contracts.pkgs.clock import BotClock
from src.contracts.pkgs.memory import MemoryCheckpoints, MemoryPolicy, MemoryReader
from src.contracts.pkgs.world import WorldJournal, WorldReader, WorldWriter
from src.contracts.rhythm import RhythmObservation
from src.kernel import BuiltinSource, compose_managed, module
from src.mcp.config import PlatformsConfig
from src.memory import Memory
from src.memory_model.config import MemoryModelConfig
from src.memory_model.rules import RuleMemoryPolicy
from src.memory_model.training import train as train_memory
from src.rhythm.config import RhythmConfig
from src.rhythm.rules import RuleRhythmPolicy
from src.rhythm.training import train as train_rhythm
from src.runtime import create_runtime
from src.utils import thaw_json
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

    from aurora import AuroraConfig
    from src.contracts.resource import ResourceRef
    from src.kernel import ManagedAssembly, ModuleContext
    from src.runtime.core import AuroraRuntime

_START = datetime(2026, 10, 18, tzinfo=UTC)
_DUE = _START + timedelta(hours=12)
_EVIDENCE = "experiment:started:7"
_GOAL = "aurora:goal/experiment"
_WAKE = "aurora:wake/experiment"
_HIDDEN_SIZE = 4
_PLANNING_STEPS = 3


def _config(
    project: Path, *, learned_rhythm: bool, learned_memory: bool
) -> tuple[AuroraConfig, ResourceRef, ResourceRef]:
    """小样本只验证真实训练权重的协作链路，不据此主张任务收益。"""
    rhythm = RuleRhythmPolicy(evoke_every=1).ref
    memory = RuleMemoryPolicy().ref
    if learned_rhythm:
        rhythm = train_rhythm(
            (make_episode("train", True, _START),),
            (make_episode("validation", True, _START + timedelta(days=1)),),
            hidden_size=_HIDDEN_SIZE,
            epochs=8,
        ).save(project / "rhythm.pt")
    if learned_memory:
        memory = train_memory(episodes("train"), episodes("validation", days=1), hidden_size=4, epochs=2).save(
            project / "memory.pt"
        )
    config = load_config(project)
    config = config.with_value(CADENCE_CONFIG, replace(config.get(CADENCE_CONFIG), enabled=False))
    config = config.with_value(
        PLATFORMS_CONFIG,
        PlatformsConfig(tuple(replace(item, enabled=False) for item in config.get(PLATFORMS_CONFIG).platforms)),
    )
    config = config.with_value(
        RHYTHM_CONFIG,
        RhythmConfig(str(rhythm.key), "rhythm.pt" if learned_rhythm else None, probability_threshold=0.1),
    )
    config = config.with_value(
        MEMORY_MODEL_CONFIG, MemoryModelConfig(str(memory.key), "memory.pt" if learned_memory else None)
    )
    return config, rhythm, memory


async def _compose(config: AuroraConfig, model: FakeModel, at: datetime) -> tuple[AuroraRuntime, ManagedAssembly]:
    """只注入时间来源；两种模型、世界、工具和认知运行均走真实装配。"""

    @module(
        name="test_cadence",
        provides=CadencePort,
        requires=(WorldReader, WorldWriter, RhythmPolicy, BotStateStore),
        priority=10,
    )
    def cadence(context: ModuleContext) -> CadencePort:
        """默认节律使用实际所选策略，手动兑现检查以消除后台时序竞争。"""
        return Cadence(
            context.get(WorldReader),
            context.get(WorldWriter),
            policy=context.get(RhythmPolicy),
            state=context.get(BotStateStore),
            now=lambda: at,
        )

    @module(
        name="test_memory",
        provides=MemoryReader,
        requires=(WorldReader, MemoryPolicy, BotStateStore, ScopeCatalog),
        priority=10,
    )
    def memory(context: ModuleContext) -> MemoryReader:
        """默认记忆使用实际所选排序器，与世界共用同一观察时间。"""
        return Memory(
            context.get(WorldReader),
            policy=context.get(MemoryPolicy),
            state=context.get(BotStateStore),
            catalog=context.get(ScopeCatalog),
            now=lambda: at,
        )

    @module(name="test_clock", provides=BotClock, requires=(BotStateStore, WorldReader), priority=10)
    def clock(context: ModuleContext) -> BotClock:
        """时间服务兑现主体保存的安排，不替换调度或恢复算法。"""
        return PersistentBotClock(context.get(BotStateStore), context.get(WorldReader), now=lambda: at)

    world = SqlAlchemyWorldJournal(config.project_root / "joint-world.sqlite3", now=lambda: at)
    handle = await compose_managed(
        config,
        (*BuiltinSource().discover(), cadence, memory, clock),
        instances=((Model, model), (WorldJournal, world)),
    )
    runtime = create_runtime(handle.assembly, output=lambda _: None)
    stop = asyncio.Event()
    stop.set()
    await handle.activate(stop)
    await handle.assembly.get(CadencePort).initialize()
    return runtime, handle


async def _first_life(config: AuroraConfig, rhythm: ResourceRef, memory: ResourceRef) -> dict[str, object]:
    """节律分配机会后，Bot 自主采用已有实验并登记未来检查。"""
    model = PlanningModel()
    runtime, handle = await _compose(config, model, _START)
    try:
        await runtime.world.append_commit(
            commit_id=_EVIDENCE,
            kind="environment.experiment.started",
            source="experiment",
            summary="operation-7 实验已经发起，等待完成后核对结果。",
            scopes=frozenset({"lab:world/experiment"}),
            based_on=WorldFrontier(),
            data={"operation_id": "operation-7"},
        )
        await handle.assembly.get(CadencePort).evaluate_once()
        assert len(model.requests) == _PLANNING_STEPS
        state = await handle.assembly.get(BotStateStore).snapshot()
        assert state.wake(_WAKE).status is WakeStatus.PENDING
        assert state.goal(_GOAL).checkpoint.evidence_refs == (_EVIDENCE,)
        facts = (await runtime.world.stream(0, 256)).commits
        planned = next(item for item in facts if item.kind == "cadence.tree_planned")
        assert planned.data["policy"] == {"key": str(rhythm.key), "revision": rhythm.revision}
        expected_size = _HIDDEN_SIZE if config.get(RHYTHM_CONFIG).weights is not None else 0
        assert len(planned.data["state"]["hidden"]) == expected_size
        requests = tuple(item for item in facts if item.kind == "engine.model.requested")
        assert len(requests) == _PLANNING_STEPS
        assert all(
            item.data["memory"]["recall"]["policy"] == {"key": str(memory.key), "revision": memory.revision}
            for item in requests
        )
        checkpoint = await handle.assembly.get(MemoryCheckpoints).save()
        assert (checkpoint is not None) == (config.get(MEMORY_MODEL_CONFIG).weights is not None)
        return handle.assembly.get(CadencePort).status()
    finally:
        await handle.close()


def _archived(config: AuroraConfig, rhythm: ResourceRef, memory: ResourceRef) -> AuroraConfig:
    """移除路径依赖，第二次启动只能按确切资源版本读取归档字节。"""
    rhythm_config = config.get(RHYTHM_CONFIG)
    if rhythm_config.weights is not None:
        (config.project_root / rhythm_config.weights).unlink()
        config = config.with_value(
            RHYTHM_CONFIG,
            replace(rhythm_config, weights=None, weights_ref=f"{rhythm.key}@{rhythm.revision}"),
        )
    memory_config = config.get(MEMORY_MODEL_CONFIG)
    if memory_config.weights is not None:
        (config.project_root / memory_config.weights).unlink()
        config = config.with_value(
            MEMORY_MODEL_CONFIG,
            replace(memory_config, weights=None, weights_ref=f"{memory.key}@{memory.revision}"),
        )
    return config


async def _second_life(
    config: AuroraConfig, rhythm: ResourceRef, memory: ResourceRef, before: dict[str, object]
) -> None:
    """没有新增输入时，主体仍能恢复到期活动及窗口外的必要证据。"""
    model = FakeModel()
    runtime, handle = await _compose(config, model, _DUE)
    try:
        assert handle.assembly.get(RhythmPolicy).ref == rhythm
        assert handle.assembly.get(MemoryPolicy).ref == memory
        assert handle.assembly.get(CadencePort).status() == before
        restored = await handle.assembly.get(MemoryCheckpoints).initialize()
        assert restored == (config.get(MEMORY_MODEL_CONFIG).weights_ref is not None)
        await handle.assembly.get(BotClock).evaluate_once()
        assert len(model.requests) == 1
        system = model.requests[0].messages[0].content
        assert "operation-7 已经发起，先查询完成状态" in system
        assert "operation-7 实验已经发起" in system
        state = await handle.assembly.get(BotStateStore).snapshot()
        assert state.wake(_WAKE).status is WakeStatus.COMPLETED
        facts = (await runtime.world.stream(0, 256)).commits
        request = tuple(item for item in facts if item.kind == "engine.model.requested")[-1]
        exposure = request.data["memory"]
        assert exposure["recall"]["policy"] == {"key": str(memory.key), "revision": memory.revision}
        assert exposure["recall"]["observed_at"] == _DUE.isoformat()
        assert _EVIDENCE in exposure["required_ids"]
        assert _EVIDENCE in exposure["included_ids"]
        assert not any(item.kind == "console.input" for item in facts)
        await _continue_rhythm(runtime, model)
    finally:
        await handle.close()


async def _continue_rhythm(runtime: AuroraRuntime, model: FakeModel) -> None:
    """重启后的第二次节律前向必须继承第一轮真实隐状态。"""
    await runtime.assembly.get(CadencePort).evaluate_once()
    facts = (await runtime.world.stream(0, 256)).commits
    plans = tuple(item for item in facts if item.kind == "cadence.tree_planned")
    first, resumed = plans
    raw = resumed.data["observation"]
    observation = RhythmObservation(
        "aurora:bot/default",
        _DUE,
        raw["cursor"],
        0,
        (_DUE - _START).total_seconds(),
        (_GOAL,),
        pending_actions=1,
        timer_due=True,
    )
    assert thaw_json(raw) == observation_data(observation)
    policy = runtime.assembly.get(RhythmPolicy)
    expected = policy.evaluate(observation, tuple(first.data["state"]["hidden"]))
    assert tuple(resumed.data["state"]["hidden"]) == expected.hidden
    if first.data["state"]["hidden"]:
        assert expected.hidden != policy.evaluate(observation).hidden
    assert len(model.requests) == len(plans)


@pytest.mark.parametrize(
    ("learned_rhythm", "learned_memory"),
    [(False, False), (True, False), (False, True), (True, True)],
    ids=["rules-rules", "gru-rules", "rules-tgn", "gru-tgn"],
)
def test_trained_rhythm_and_memory_preserve_self_scheduled_activity_after_restart(
    configured_project: Path, learned_rhythm: bool, learned_memory: bool
) -> None:
    """规则与实际 GRU/TGN 的四种组合均能跨过一次无新输入的主体重启。"""
    config, rhythm, memory = _config(configured_project, learned_rhythm=learned_rhythm, learned_memory=learned_memory)

    async def scenario() -> None:
        """先由环境唤起，再通过独立新装配兑现主体自己的等待。"""
        before = await _first_life(config, rhythm, memory)
        await _second_life(_archived(config, rhythm, memory), rhythm, memory, before)

    asyncio.run(scenario())
