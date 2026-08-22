from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.contracts import EnvironmentEvent, WorldFrontier
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path


EXPECTED_EVENT_COUNT = 2


def test_sqlalchemy_journal_persists_scoped_events_and_delta(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", page_size=1)
        await journal.initialize()
        first = await journal.append_event(
            EnvironmentEvent("event-1", "test", "qq:group:1", "message", datetime.now(UTC), "第一条")
        )
        duplicate = await journal.append_event(
            EnvironmentEvent("event-1", "test", "qq:group:1", "message", first.occurred_at, "第一条")
        )
        await journal.append_event(
            EnvironmentEvent("event-2", "test", "qq:group:1", "message", datetime.now(UTC), "第二条")
        )

        assert duplicate == first
        assert (await journal.head(frozenset({"qq:group:1"}))).sequence("qq:group:1") == EXPECTED_EVENT_COUNT
        page = await journal.delta(WorldFrontier(), frozenset({"qq:group:1"}))
        assert [commit.commit_id for commit in page.commits] == ["event-1"]
        assert page.has_more is True
        await journal.close()

    asyncio.run(scenario())
