"""时区表示、持久化时刻和重试身份必须描述同一个事实。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from src.contracts import EnvironmentEvent, WorldCommit, WorldCommitInput, WorldFrontier
from src.contracts.memory import MemoryRequest
from src.memory import Memory
from src.memory_model.rules import RuleMemoryPolicy
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def test_timezones_preserve_actual_occurrence_and_knowledge_after_sqlite_roundtrip(tmp_path: Path) -> None:
    """SQLite 不保留时区信息时，存储前仍需保持实际瞬间和记忆可见边界。"""

    async def scenario() -> None:
        east = timezone(timedelta(hours=8))
        west = timezone(timedelta(hours=-5))
        clock = [_NOW.astimezone(east)]
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: clock[0])
        try:
            await world.initialize()
            event = EnvironmentEvent("fact", "test", "test:world", "message", _NOW.astimezone(west), "第一项")
            first = await world.append_event(event)
            assert first.occurred_at == _NOW
            assert first.recorded_at == _NOW
            assert first.occurred_at.tzinfo is UTC
            assert first.recorded_at is not None and first.recorded_at.tzinfo is UTC
            assert await world.commit(event.event_id) == first
            clock[0] = (_NOW + timedelta(seconds=1)).astimezone(west)
            second = await world.append_event(replace(event, event_id="second", occurred_at=clock[0]))
            assert second.recorded_at == _NOW + timedelta(seconds=1)
            assert second.occurred_at == second.recorded_at
            snapshot = await Memory(world, policy=RuleMemoryPolicy()).recall(MemoryRequest(observed_at=_NOW))
            assert {commit.commit_id for scope in snapshot.scopes for commit in scope.commits} == {"fact"}
        finally:
            await world.close()

    asyncio.run(scenario())


def test_retries_can_change_timezone_representation_but_not_the_occurrence_instant(tmp_path: Path) -> None:
    """同一瞬间的不同表示可重试，改写事件时间必须使用新的事实身份。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: _NOW)
        try:
            await world.initialize()
            event = EnvironmentEvent("fact", "test", "test:world", "message", _NOW, "原始事实")
            first = await world.append_event(event)
            equivalent = replace(event, occurred_at=_NOW.astimezone(timezone(timedelta(hours=8))))
            assert await world.append_event(equivalent) == first
            with pytest.raises(ValueError, match="不同内容"):
                await world.append_event(replace(event, occurred_at=_NOW + timedelta(seconds=1)))
            assert await world.cursor() == first.cursor
        finally:
            await world.close()

    asyncio.run(scenario())


def test_world_contracts_reject_ambiguous_naive_event_times() -> None:
    """时区缺失不能靠运行机器的本地设置解释为世界事实。"""
    naive = _NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="时区"):
        EnvironmentEvent("fact", "test", "test:world", "message", naive, "事实")
    with pytest.raises(ValueError, match="时区"):
        WorldCommitInput(
            "fact", "message", "test", "事实", frozenset({"test:world"}), WorldFrontier(), occurred_at=naive
        )
    with pytest.raises(ValueError, match="时区"):
        WorldCommit("fact", "message", "test", "事实", naive, {"test:world": 1}, WorldFrontier())
