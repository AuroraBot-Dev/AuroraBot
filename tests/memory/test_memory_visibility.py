"""记忆恢复以获知边界为准，不使用迟到事实或未来主体选择。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from aurora_bot.bot.store import JournalBotState
from aurora_bot.contracts.bot import BotChange, Goal, GoalStatus
from aurora_bot.contracts.memory import MemoryRequest
from aurora_bot.contracts.world import MemoryScopeSnapshot, WorldFrontier
from aurora_bot.memory import Memory
from aurora_bot.memory_model.rules import RuleMemoryPolicy
from aurora_bot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path


def test_memory_observation_and_cursor_exclude_late_and_future_information(tmp_path: Path) -> None:
    """实时索引经过后续事件后，历史经历、域头和主体仍能准确恢复。"""

    async def scenario() -> None:
        first = datetime(2026, 10, 18, tzinfo=UTC)
        clock = [first]
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: clock[0])
        state = JournalBotState(world, "aurora:bot/test")
        goal = Goal("aurora:goal/check", "检查", "完成核对")
        try:
            await state.apply(BotChange("create", 0, (goal,)))
            await _fact(world, "known", first, "已经知道")
            cutoff = await world.cursor()
            clock[0] += timedelta(minutes=1)
            await _fact(world, "late", first - timedelta(minutes=5), "稍后才知道")
            await _fact(world, "future", first + timedelta(hours=1), "未来发生")
            await state.apply(BotChange("pause", 1, (replace(goal, status=GoalStatus.PAUSED),)))
            memory = Memory(world, policy=RuleMemoryPolicy(), state=state)
            current = await memory.recall(MemoryRequest(observed_at=clock[0]))
            assert _ids(current.scopes) == {"known", "late", "aurora:bot/test:state:1", "aurora:bot/test:state:2"}
            assert current.continuity is not None
            assert current.continuity.goals == ()
            assert current.continuity.goal_counts == (("paused", 1),)

            history = await memory.recall(MemoryRequest(observed_at=first))
            bounded = await memory.recall(MemoryRequest(cursor=cutoff, observed_at=clock[0]))
            for snapshot in (history, bounded):
                assert _ids(snapshot.scopes) == {"aurora:bot/test:state:1", "known"}
                assert snapshot.recall is not None
                assert snapshot.recall.request.cursor == cutoff
                assert snapshot.continuity is not None
                assert snapshot.continuity.goals[0].status is GoalStatus.ACTIVE
                assert next(scope for scope in snapshot.scopes if scope.scope == "test:world/facts").head == 1
            rebuilt = await Memory(world, policy=RuleMemoryPolicy(), state=state).recall(
                MemoryRequest(observed_at=first)
            )
            assert rebuilt == history
            assert (await state.snapshot()).goal(goal.goal_id).status is GoalStatus.PAUSED
            empty = await memory.recall(MemoryRequest(cursor=0, observed_at=clock[0]))
            assert empty.scopes == ()
            assert empty.continuity is not None and empty.continuity.goals == ()
            with pytest.raises(ValueError, match="超出"):
                await memory.recall(MemoryRequest(cursor=99))
        finally:
            await world.close()

    asyncio.run(scenario())


async def _fact(world: SqlAlchemyWorldJournal, identity: str, occurred_at: datetime, summary: str) -> None:
    """将事件时间与测试时钟提供的获知时间分开提交。"""
    await world.append_commit(
        commit_id=identity,
        kind="environment.fact",
        source="test",
        summary=summary,
        scopes=frozenset({"test:world/facts"}),
        based_on=WorldFrontier(),
        data={},
        occurred_at=occurred_at,
    )


def _ids(scopes: tuple[MemoryScopeSnapshot, ...]) -> set[str]:
    """汇总跨域提交身份，忽略同一提交的多域投影。"""
    return {commit.commit_id for scope in scopes for commit in scope.commits}
