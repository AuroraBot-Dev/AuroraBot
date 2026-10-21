"""主体历史快照不能包含未来选择，也不能改变当前状态。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from aurora_bot.bot.store import JournalBotState
from aurora_bot.contracts.bot import BotChange, Goal, GoalStatus
from aurora_bot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path


def test_historical_subject_view_does_not_leak_future_goal_updates(tmp_path: Path) -> None:
    """读取截至指定世界游标的选择，后续暂停不会穿越到过去。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/test")
        goal = Goal("aurora:goal/check", "核对结果", "结果已确认")
        try:
            await state.apply(BotChange("create", 0, (goal,)))
            cursor = await world.cursor()
            await state.apply(BotChange("pause", 1, (replace(goal, status=GoalStatus.PAUSED),)))
            history = await state.snapshot_at(cursor)
            assert history.goal(goal.goal_id).status is GoalStatus.ACTIVE
            assert (await state.snapshot()).goal(goal.goal_id).status is GoalStatus.PAUSED
            assert (await state.snapshot_at(0)).goals == ()
        finally:
            await world.close()

    asyncio.run(scenario())
