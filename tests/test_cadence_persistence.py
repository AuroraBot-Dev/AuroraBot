"""验证节律时间安排、隐状态和未完成交付能够跨进程恢复。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from test_cadence import FakeLauncher

from aurorabot.cadence import Cadence
from aurorabot.contracts import MCP_EVENT_RECEIVED, TreeLaunchRequest, WorldFrontier
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.contracts.rhythm import RhythmAction, RhythmDecision, RhythmObservation, RhythmPrediction
from aurorabot.rhythm.rules import RuleRhythmPolicy
from aurorabot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


@dataclass(slots=True)
class Clock:
    """测试通过显式推进时间触发节律，无需现实等待。"""

    value: datetime = _NOW

    def __call__(self) -> datetime:
        """返回当前确定时间。"""
        return self.value


@dataclass(slots=True)
class RecurrentPolicy:
    """观察每次判断收到的循环状态。"""

    revision: str = "1"
    seen: list[tuple[float, ...]] = field(default_factory=list)

    @property
    def ref(self) -> ResourceRef:
        """可切换版本以检验隐状态隔离。"""
        return ResourceRef(ResourceKey.parse("test:rhythm/model/recurrent"), self.revision)

    @property
    def parameters(self) -> dict[str, float | int]:
        """测试策略没有可变推理参数。"""
        return {}

    def evaluate(self, observation: RhythmObservation, hidden: tuple[float, ...] = ()) -> RhythmPrediction:
        """用明确状态计数模拟循环模型，时间到达后分配推理机会。"""
        self.seen.append(hidden)
        action = RhythmAction.DELIBERATE if observation.timer_due else RhythmAction.WAIT
        decision = RhythmDecision(action, observation.observed_at + timedelta(seconds=60), "检查节律状态")
        return RhythmPrediction(decision, ((hidden[0] if hidden else 0) + 1,))


async def _event(world: SqlAlchemyWorldJournal, event_id: str) -> None:
    """提交一条可观察的外部变化。"""
    await world.append_commit(
        commit_id=event_id,
        kind=MCP_EVENT_RECEIVED,
        source="test",
        summary="环境变化",
        scopes=frozenset({"test:world"}),
        based_on=WorldFrontier(),
        data={},
        occurred_at=_NOW,
    )


def test_clock_alone_can_allocate_cognition_without_external_messages(tmp_path: Path) -> None:
    """持续安静也能唤起 Bot，自身日志不会无限放大压力。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await world.initialize()
        clock = Clock()
        launcher = FakeLauncher()
        cadence = Cadence(world, world, policy=RuleRhythmPolicy(max_idle_seconds=60), launcher=launcher, now=clock)
        try:
            await cadence.evaluate_once()
            assert launcher.requests == []
            clock.value += timedelta(seconds=60)
            await cadence.evaluate_once()
            await cadence.evaluate_once()
            assert len(launcher.requests) == 1
            records = await world.commits(cadence.scope, 0, 20)
            decisions = [commit for commit in records if "decision" in commit.data]
            assert [commit.data["decision"]["action"] for commit in decisions] == ["wait", "deliberate"]
            assert decisions[-1].data["observation"]["pending_events"] == 0
        finally:
            await world.close()

    asyncio.run(scenario())


def test_restart_preserves_cursor_waiting_pressure_and_recurrent_state(tmp_path: Path) -> None:
    """恢复后不重新消费旧事件，模型收到先前保存的隐状态。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await world.initialize()
        clock = Clock()
        first = Cadence(world, world, policy=RecurrentPolicy(), launcher=FakeLauncher(), now=clock)
        try:
            await _event(world, "first")
            await first.evaluate_once()
            await world.close()
            world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
            await world.initialize()
            policy = RecurrentPolicy()
            restarted = Cadence(world, world, policy=policy, launcher=FakeLauncher(), now=clock)
            await restarted.evaluate_once()
            assert restarted.status()["pending"] == 1
            assert policy.seen == []
            await _event(world, "second")
            await restarted.evaluate_once()
            assert policy.seen == [(1.0,)]
            previous_pending = first.status()["pending"]
            assert isinstance(previous_pending, int)
            assert restarted.status()["pending"] == previous_pending + 1
        finally:
            await world.close()

    asyncio.run(scenario())


def test_policy_revision_change_clears_incompatible_hidden_state(tmp_path: Path) -> None:
    """消费游标保留，权重版本不兼容的状态不会混用。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await world.initialize()
        clock = Clock()
        try:
            await _event(world, "first")
            first = Cadence(world, world, policy=RecurrentPolicy(), launcher=FakeLauncher(), now=clock)
            await first.evaluate_once()
            changed = RecurrentPolicy("2")
            restarted = Cadence(world, world, policy=changed, launcher=FakeLauncher(), now=clock)
            await restarted.evaluate_once()
            assert changed.seen == [()]
        finally:
            await world.close()

    asyncio.run(scenario())


def test_internal_bookkeeping_cannot_postpone_a_due_time_check(tmp_path: Path) -> None:
    """内部日志持续到达时，计时判断仍可按期获得一次推理机会。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await world.initialize()
        clock = Clock()
        launcher = FakeLauncher()
        cadence = Cadence(world, world, policy=RuleRhythmPolicy(max_idle_seconds=60), launcher=launcher, now=clock)
        try:
            await cadence.evaluate_once()
            await world.append_commit(
                commit_id="engine-noise",
                kind="engine.model.completed",
                source="engine",
                summary="内部记录",
                scopes=frozenset({"test:run"}),
                based_on=WorldFrontier(),
                data={},
            )
            previous_head = await world.cursor()
            clock.value += timedelta(seconds=60)
            await cadence.evaluate_once()
            records = await world.commits(cadence.scope, 0, 20)
            decision = next(commit for commit in records if commit.kind == "cadence.tree_planned")
            assert decision.data["observation"]["cursor"] < previous_head
            assert len(launcher.requests) == 1
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("already_started", [False, True])
def test_restart_delivers_only_cognition_that_was_confirmed_not_started(tmp_path: Path, already_started: bool) -> None:
    """崩溃窗口以引擎记录核对，已经开始的认知不会被重复启动。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await world.initialize()
        captured: list[TreeLaunchRequest] = []

        class InterruptedLauncher(FakeLauncher):
            """模拟安排落库后、认知开始前后两种中断窗口。"""

            async def launch_tree(self, request: TreeLaunchRequest):
                """保存运行身份后中断，不返回虚假成功。"""
                captured.append(request)
                if already_started:
                    await world.append_commit(
                        commit_id=f"{request.tree_id}:tree:started",
                        kind="engine.tree.started",
                        source="engine",
                        summary="认知已经开始",
                        scopes=frozenset({"test:run"}),
                        based_on=WorldFrontier(),
                        data={},
                    )
                raise asyncio.CancelledError

        clock = Clock()
        try:
            await _event(world, "first")
            first = Cadence(
                world, world, policy=RuleRhythmPolicy(evoke_every=1), launcher=InterruptedLauncher(), now=clock
            )
            with pytest.raises(asyncio.CancelledError):
                await first.evaluate_once()
            launcher = FakeLauncher()
            restarted = Cadence(world, world, policy=RuleRhythmPolicy(evoke_every=1), launcher=launcher, now=clock)
            await restarted.evaluate_once()
            if already_started:
                assert launcher.requests == []
                records = await world.commits(restarted.scope, 0, 20)
                assert any(commit.data.get("status") == "interrupted" for commit in records)
            else:
                assert launcher.requests[0].tree_id == captured[0].tree_id
        finally:
            await world.close()

    asyncio.run(scenario())
