from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from src.contracts import EnvironmentEvent, WorldCommitInput, WorldFrontier
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
        with pytest.raises(ValueError, match="不同内容"):
            await journal.append_event(
                EnvironmentEvent("event-1", "test", "qq:group:1", "message", first.occurred_at, "冲突")
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


def test_sqlalchemy_journal_assigns_one_batch_of_sequences_atomically(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        commits = await journal.append_commits(
            (
                WorldCommitInput("commit-1", "tool.requested", "test", "第一项", frozenset({"scope"}), WorldFrontier()),
                WorldCommitInput("commit-2", "tool.requested", "test", "第二项", frozenset({"scope"}), WorldFrontier()),
            )
        )

        assert [commit.scopes["scope"] for commit in commits] == [1, 2]
        await journal.close()

    asyncio.run(scenario())


def test_sqlalchemy_journal_reads_bodies_by_id_and_bounded_scope_range(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        await journal.append_commits(
            (
                WorldCommitInput("c-1", "tool.succeeded", "test", "第一项", frozenset({"scope"}), WorldFrontier()),
                WorldCommitInput("c-2", "tool.failed", "test", "第二项", frozenset({"scope"}), WorldFrontier()),
                WorldCommitInput("c-3", "tool.succeeded", "test", "第三项", frozenset({"scope"}), WorldFrontier()),
            )
        )

        found = await journal.commit("c-2")
        assert found is not None and found.data == {}
        assert await journal.commit("missing") is None
        assert [item.commit_id for item in await journal.commits("scope", 1, 10)] == ["c-2", "c-3"]
        assert [item.commit_id for item in await journal.commits("scope", 0, 2)] == ["c-1", "c-2"]
        assert await journal.commits("scope", 3, 10) == ()
        await journal.close()

    asyncio.run(scenario())


def test_sqlalchemy_journal_derives_forest_index_from_engine_commits(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        later = datetime.now(UTC)
        earlier = later - timedelta(seconds=5)
        await journal.append_commits(
            (
                WorldCommitInput(
                    "a-1",
                    "tool.requested",
                    "engine",
                    "请求",
                    frozenset({"aurora:tree:a"}),
                    WorldFrontier(),
                    {"tree_id": "a", "tool": "x"},
                    later,
                ),
                WorldCommitInput(
                    "a-2",
                    "tool.succeeded",
                    "engine",
                    "完成",
                    frozenset({"aurora:tree:a"}),
                    WorldFrontier(),
                    {"tree_id": "a", "tool": "x"},
                    later,
                ),
                WorldCommitInput(
                    "b-1",
                    "tool.requested",
                    "engine",
                    "请求",
                    frozenset({"aurora:tree:b"}),
                    WorldFrontier(),
                    {"tree_id": "b", "tool": "y"},
                    earlier,
                ),
            )
        )

        index = await journal.tree_index(10)
        assert [item.tree_id for item in index] == ["a", "b"]
        assert [item.commit_count for item in index] == [2, 1]
        assert index[0].first_seen <= index[0].last_seen
        assert index[0].first_seen == later and index[1].last_seen == earlier
        assert await journal.tree_index(1) == index[:1]
        await journal.close()

    asyncio.run(scenario())


def test_sqlalchemy_journal_rejects_invalid_query_bounds(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        with pytest.raises(ValueError, match="scope"):
            await journal.commits("", 0, 10)
        with pytest.raises(ValueError, match="after"):
            await journal.commits("scope", -1, 10)
        with pytest.raises(ValueError, match="limit"):
            await journal.commits("scope", 0, 0)
        with pytest.raises(ValueError, match="limit"):
            await journal.tree_index(0)
        with pytest.raises(ValueError, match="commit_id"):
            await journal.commit("")
        await journal.close()

    asyncio.run(scenario())
