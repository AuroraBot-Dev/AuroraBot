"""事件发生时间、Bot 获知时间与全局可见顺序的持久验证。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from aurora_bot.contracts import EnvironmentEvent
from aurora_bot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def test_late_fact_keeps_occurrence_time_and_receives_actual_knowledge_boundary(tmp_path: Path) -> None:
    """回填旧事件不能把获知时间伪装成过去，重复提交也不推进边界。"""

    async def scenario() -> None:
        path = tmp_path / "world.sqlite3"
        world = SqlAlchemyWorldJournal(path, now=lambda: _NOW)
        await world.initialize()
        event = EnvironmentEvent("late", "test", "test:world", "fact", _NOW - timedelta(days=10), "迟到的事实")
        try:
            first = await world.append_event(event)
            retry = await world.append_event(event)
            assert first == retry
            assert first.cursor == await world.cursor() == 1
            assert first.recorded_at == _NOW
            assert first.occurred_at == event.occurred_at
            await world.close()
            world = SqlAlchemyWorldJournal(path)
            await world.initialize()
            assert await world.commit("late") == first
        finally:
            await world.close()

    asyncio.run(scenario())


def test_global_cursor_orders_facts_across_independent_scopes(tmp_path: Path) -> None:
    """域内编号互不共享，全局游标仍能冻结统一读取截点。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: _NOW)
        await world.initialize()
        try:
            first = await world.append_event(EnvironmentEvent("a", "test", "a:world", "fact", _NOW, "第一项"))
            second = await world.append_event(EnvironmentEvent("b", "test", "b:world", "fact", _NOW, "第二项"))
            assert first.scopes["a:world"] == second.scopes["b:world"] == 1
            assert first.cursor < second.cursor
            page = await world.stream(0, 10)
            assert [item.cursor for item in page.commits] == [first.cursor, second.cursor]
        finally:
            await world.close()

    asyncio.run(scenario())


def test_clock_adjustment_cannot_move_knowledge_time_backwards(tmp_path: Path) -> None:
    """记录顺序保持明确，即便系统时钟回拨也不能回填获知时间。"""

    async def scenario() -> None:
        clock = [_NOW]
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: clock[0])
        await world.initialize()
        try:
            first = await world.append_event(EnvironmentEvent("a", "test", "test:world", "fact", _NOW, "第一项"))
            clock[0] -= timedelta(minutes=1)
            second = await world.append_event(EnvironmentEvent("b", "test", "test:world", "fact", _NOW, "第二项"))
            assert second.cursor > first.cursor
            assert second.recorded_at == first.recorded_at
        finally:
            await world.close()

    asyncio.run(scenario())
