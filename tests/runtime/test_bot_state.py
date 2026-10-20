"""验证主体状态的持久恢复、版本冲突和自主选择。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurorabot.bot.store import JournalBotState
from aurorabot.contracts.bot import BotChange, Checkpoint, Goal, GoalStatus, StateConflictError, WakePlan, WakeStatus
from aurorabot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
_GOAL = Goal(
    "aurora:goal/experiment",
    "核对实验结果",
    "结果经过比较并保存",
    checkpoint=Checkpoint(
        stage="等待实验完成",
        confirmed=("已发起实验 operation-7",),
        pending_actions=("核对 operation-7 的完成状态",),
        evidence_refs=("experiment:started:7",),
    ),
)
_WAKE = WakePlan("aurora:wake/experiment", _NOW, "检查实验结果", _GOAL.goal_id)


def test_bot_recovers_choices_checkpoints_and_arrangements_from_world(tmp_path: Path) -> None:
    """关闭数据库后，新主体实例可恢复完整选择。"""

    async def scenario() -> None:
        path = tmp_path / "world.sqlite3"
        world = SqlAlchemyWorldJournal(path)
        state = JournalBotState(world, "aurora:bot/aurora")
        original = await state.apply(BotChange("accept", 0, (_GOAL,), (_WAKE,)))
        await world.close()
        reopened = SqlAlchemyWorldJournal(path)
        try:
            restored = await JournalBotState(reopened, state.bot_id).snapshot()
            assert restored == original
            assert restored.goal(_GOAL.goal_id).checkpoint.pending_actions == _GOAL.checkpoint.pending_actions
        finally:
            await reopened.close()

    asyncio.run(scenario())


def test_retries_are_idempotent_after_later_updates_and_restart(tmp_path: Path) -> None:
    """旧命令重试不会覆盖后续选择，复用身份改变内容会失败。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/aurora")
        change = BotChange("accept", 0, (_GOAL,))
        try:
            await state.apply(change)
            updated = await state.apply(BotChange("pause", 1, (replace(_GOAL, status=GoalStatus.PAUSED),)))
            restored = JournalBotState(world, state.bot_id)
            snapshot = await restored.apply(change)
            assert snapshot.version == updated.version
            assert snapshot.goal(_GOAL.goal_id).status is GoalStatus.PAUSED
            with pytest.raises(ValueError, match="命令身份"):
                await restored.apply(BotChange("accept", 0, (replace(_GOAL, purpose="另一件事"),)))
        finally:
            await world.close()

    asyncio.run(scenario())


def test_stale_version_cannot_override_another_choice(tmp_path: Path) -> None:
    """同一主体的独立读取者必须重新核对新版本。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        first = JournalBotState(world, "aurora:bot/aurora")
        second = JournalBotState(world, first.bot_id)
        try:
            await first.apply(BotChange("accept", 0, (_GOAL,)))
            with pytest.raises(StateConflictError, match="状态已变化"):
                await second.apply(BotChange("stale", 0, (replace(_GOAL, status=GoalStatus.ABANDONED),)))
            assert (await second.snapshot()).goal(_GOAL.goal_id).status is GoalStatus.ACTIVE
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [GoalStatus.PAUSED, GoalStatus.COMPLETED, GoalStatus.ABANDONED])
def test_stopping_goal_cancels_pending_wakes_atomically(tmp_path: Path, status: GoalStatus) -> None:
    """目标状态与停止安排在同一提交中发生。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/aurora")
        try:
            await state.apply(BotChange("accept", 0, (_GOAL,), (_WAKE,)))
            snapshot = await state.apply(BotChange("stop", 1, (replace(_GOAL, status=status),)))
            assert snapshot.wake(_WAKE.wake_id).status is WakeStatus.CANCELLED
            assert await JournalBotState(world, state.bot_id).snapshot() == snapshot
        finally:
            await world.close()

    asyncio.run(scenario())


def test_invalid_arrangements_leave_no_partial_goal_update(tmp_path: Path) -> None:
    """原子修改中出现无效引用时，目标也不写入。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/aurora")
        try:
            invalid = replace(_WAKE, goal_id="aurora:goal/missing")
            with pytest.raises(ValueError, match="不存在的目标"):
                await state.apply(BotChange("invalid", 0, (_GOAL,), (invalid,)))
            assert (await state.snapshot()).version == 0
            assert await world.cursor() == 0
        finally:
            await world.close()

    asyncio.run(scenario())


def test_wake_identity_cannot_be_reused_or_rescheduled(tmp_path: Path) -> None:
    """安排的意图和时间固定，终止后不能回到待交付状态。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/aurora")
        try:
            await state.apply(BotChange("accept", 0, (_GOAL,), (_WAKE,)))
            with pytest.raises(ValueError, match="新建安排"):
                await state.apply(BotChange("reschedule", 1, wakes=(replace(_WAKE, message="另一件事"),)))
            cancelled = replace(_WAKE, status=WakeStatus.CANCELLED)
            await state.apply(BotChange("cancel", 1, wakes=(cancelled,)))
            with pytest.raises(ValueError, match="新建安排"):
                await state.apply(BotChange("reuse", 2, wakes=(_WAKE,)))
        finally:
            await world.close()

    asyncio.run(scenario())


def test_bot_identities_have_independent_state(tmp_path: Path) -> None:
    """同一世界中的主体使用独立版本与状态域。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        first = JournalBotState(world, "aurora:bot/first")
        second = JournalBotState(world, "aurora:bot/second")
        try:
            await first.apply(BotChange("accept", 0, (_GOAL,)))
            assert (await second.snapshot()).goals == ()
            assert first.scope != second.scope
        finally:
            await world.close()

    asyncio.run(scenario())


def test_domain_objects_reject_ambiguous_time_and_duplicate_identity() -> None:
    """拒绝无时区时间和无法确定语义的状态输入。"""
    with pytest.raises(ValueError, match="时区"):
        replace(_WAKE, due_at=_NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="重复"):
        BotChange("duplicate", 0, (_GOAL, _GOAL))
    with pytest.raises(ValueError, match="非空文本"):
        Checkpoint(confirmed=("",))
