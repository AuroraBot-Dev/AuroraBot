"""验证未来活动的交付、取消、故障和重启核对。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from aurora_bot.bot.store import JournalBotState
from aurora_bot.clock import PersistentBotClock
from aurora_bot.contracts import AgentDefinition, AgentTree, TreeLaunchRequest, WorldFrontier
from aurora_bot.contracts.bot import BotChange, Goal, GoalStatus, WakePlan, WakeStatus
from aurora_bot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
_GOAL = Goal("aurora:goal/check", "检查结果", "确认结果")
_WAKE = WakePlan("aurora:wake/check", _NOW, "核对先前发起的操作", _GOAL.goal_id)
_AGENT = AgentDefinition(
    "aurora:agent/definition/root",
    "认知",
    "aurora:prompt/agent/root",
    "test:ai/endpoint/fake",
    frozenset(),
    frozenset(),
)


@dataclass(slots=True)
class FakeLauncher:
    """记录实际启动的认知，可模拟故障与正常结束。"""

    requests: list[TreeLaunchRequest] = field(default_factory=list)
    failure: Exception | None = None
    stop: asyncio.Event | None = None

    async def launch_tree(self, request: TreeLaunchRequest) -> AgentTree:
        """执行一次确定的认知，不访问模型或网络。"""
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        if self.stop is not None:
            self.stop.set()
        tree = AgentTree.create(request.tree_id or "test", "root", _AGENT, request.message, request.frontier)
        return tree.complete("root", "已核对")


def test_due_wake_survives_restart_and_runs_once_without_external_input(tmp_path: Path) -> None:
    """到期前保持安静，重启后可兑现安排且不重复启动。"""

    async def scenario() -> None:
        path = tmp_path / "world.sqlite3"
        world = SqlAlchemyWorldJournal(path)
        await JournalBotState(world, "aurora:bot/test").apply(BotChange("plan", 0, (_GOAL,), (_WAKE,)))
        await world.close()
        reopened = SqlAlchemyWorldJournal(path)
        state = JournalBotState(reopened, "aurora:bot/test")
        launcher = FakeLauncher()
        clock = PersistentBotClock(state, reopened)
        clock.bind_launcher(launcher)
        try:
            await clock.evaluate_once(_NOW - timedelta(seconds=1))
            assert launcher.requests == []
            await clock.evaluate_once(_NOW)
            await clock.evaluate_once(_NOW + timedelta(hours=1))
            assert len(launcher.requests) == 1
            assert launcher.requests[0].tree_id == clock.tree_id(_WAKE)
            assert launcher.requests[0].focus_goal_ids == (_GOAL.goal_id,)
            cause_id = launcher.requests[0].caused_by
            assert cause_id is not None and await reopened.commit(cause_id) is not None
            assert _GOAL.goal_id in launcher.requests[0].message
            assert (await state.snapshot()).wake(_WAKE.wake_id).status is WakeStatus.COMPLETED
        finally:
            await reopened.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("marker", "expected"),
    [("completed", WakeStatus.COMPLETED), ("failed", WakeStatus.FAILED), ("started", WakeStatus.INTERRUPTED)],
)
def test_restart_reconciles_started_runs_without_replaying_actions(
    tmp_path: Path, marker: str, expected: WakeStatus
) -> None:
    """已开始的认知依据记录核对，未知结果明确标记中断。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/test")
        await state.apply(BotChange("plan", 0, (_GOAL,), (_WAKE,)))
        await state.apply(BotChange("claim", 1, wakes=(replace(_WAKE, status=WakeStatus.RUNNING),)))
        clock = PersistentBotClock(JournalBotState(world, state.bot_id), world)
        tree_id = clock.tree_id(_WAKE)
        await world.append_commit(
            commit_id=f"{tree_id}:tree:{marker}",
            kind=f"engine.tree.{marker}",
            source="engine",
            summary="认知记录",
            scopes=frozenset({f"aurora:run/{tree_id}"}),
            based_on=WorldFrontier(),
            data={},
            occurred_at=_NOW,
        )
        launcher = FakeLauncher()
        clock.bind_launcher(launcher)
        try:
            await clock.evaluate_once(_NOW)
            assert launcher.requests == []
            assert (await state.snapshot()).wake(_WAKE.wake_id).status is expected
        finally:
            await world.close()

    asyncio.run(scenario())


def test_crash_before_cognition_started_keeps_arrangement_deliverable(tmp_path: Path) -> None:
    """交付记录已写入但认知尚未开始时，可使用同一运行身份继续。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/test")
        await state.apply(BotChange("plan", 0, (_GOAL,), (_WAKE,)))
        await state.apply(BotChange("claim", 1, wakes=(replace(_WAKE, status=WakeStatus.RUNNING),)))
        launcher = FakeLauncher()
        clock = PersistentBotClock(JournalBotState(world, state.bot_id), world)
        clock.bind_launcher(launcher)
        try:
            await clock.evaluate_once(_NOW)
            assert len(launcher.requests) == 1
            assert (await state.snapshot()).wake(_WAKE.wake_id).status is WakeStatus.COMPLETED
        finally:
            await world.close()

    asyncio.run(scenario())


def test_goal_pause_prevents_scheduled_cognition(tmp_path: Path) -> None:
    """Bot 选择暂缓目标后，时间到达也不启动认知。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/test")
        await state.apply(BotChange("plan", 0, (_GOAL,), (_WAKE,)))
        await state.apply(BotChange("pause", 1, (replace(_GOAL, status=GoalStatus.PAUSED),)))
        launcher = FakeLauncher()
        clock = PersistentBotClock(state, world)
        clock.bind_launcher(launcher)
        try:
            await clock.evaluate_once(_NOW)
            assert launcher.requests == []
        finally:
            await world.close()

    asyncio.run(scenario())


def test_cognition_failure_is_persisted_and_not_retried_implicitly(tmp_path: Path) -> None:
    """失败会成为可供 Bot 判断的状态，不循环重复行动。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/test")
        await state.apply(BotChange("plan", 0, (_GOAL,), (_WAKE,)))
        launcher = FakeLauncher(failure=RuntimeError("推理不可用"))
        clock = PersistentBotClock(state, world)
        clock.bind_launcher(launcher)
        try:
            await clock.evaluate_once(_NOW)
            await clock.evaluate_once(_NOW)
            assert len(launcher.requests) == 1
            result = (await state.snapshot()).wake(_WAKE.wake_id)
            assert result.status is WakeStatus.FAILED
            assert "推理不可用" in result.detail
        finally:
            await world.close()

    asyncio.run(scenario())


def test_clock_loop_honors_stop_after_cognition(tmp_path: Path) -> None:
    """主循环在停止请求后结束，不需要外部新事件。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/test")
        await state.apply(BotChange("plan", 0, (_GOAL,), (_WAKE,)))
        stop = asyncio.Event()
        launcher = FakeLauncher(stop=stop)
        clock = PersistentBotClock(state, world, now=lambda: _NOW)
        clock.bind_launcher(launcher)
        try:
            await asyncio.wait_for(clock.run(stop), timeout=1)
            assert stop.is_set()
        finally:
            await world.close()

    asyncio.run(scenario())
