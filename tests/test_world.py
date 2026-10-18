from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from src.contracts import EnvironmentEvent, WorldCommitInput, WorldFrontier
from src.world import SqlAlchemyWorldJournal
from src.world.migration import TARGET_VERSION

if TYPE_CHECKING:
    from pathlib import Path


EXPECTED_EVENT_COUNT = 2
_FIRST_PAGE_END = 2
_COMMIT_COUNT = 3
_RECENT_COMMIT_COUNT = 2
_CADENCE_EVOKE_EVERY = 5
_BULK_COMMIT_COUNT = 48
_DELTA_STATEMENT_BUDGET = 6
_V1_SCHEMA = (
    "CREATE TABLE schema_meta (singleton INTEGER NOT NULL, version INTEGER NOT NULL, PRIMARY KEY (singleton))",
    "CREATE TABLE world_commits (insertion_sequence INTEGER NOT NULL, commit_id VARCHAR NOT NULL, "
    "kind VARCHAR NOT NULL, source VARCHAR NOT NULL, summary VARCHAR NOT NULL, occurred_at DATETIME NOT NULL, "
    "payload JSON NOT NULL, PRIMARY KEY (insertion_sequence), UNIQUE (commit_id))",
    "CREATE TABLE world_commit_scopes (id INTEGER NOT NULL, commit_id VARCHAR NOT NULL, scope VARCHAR NOT NULL, "
    "sequence INTEGER NOT NULL, PRIMARY KEY (id), "
    "CONSTRAINT world_commit_scope_sequence_unique UNIQUE (scope, sequence), "
    "CONSTRAINT world_commit_scope_membership_unique UNIQUE (commit_id, scope), "
    "FOREIGN KEY(commit_id) REFERENCES world_commits (commit_id))",
    "CREATE TABLE world_commit_bases (id INTEGER NOT NULL, commit_id VARCHAR NOT NULL, scope VARCHAR NOT NULL, "
    "sequence INTEGER NOT NULL, PRIMARY KEY (id), "
    "CONSTRAINT world_commit_base_unique UNIQUE (commit_id, scope), "
    "FOREIGN KEY(commit_id) REFERENCES world_commits (commit_id))",
    "INSERT INTO schema_meta (singleton, version) VALUES (1, 1)",
    "INSERT INTO world_commits (commit_id, kind, source, summary, occurred_at, payload) "
    "VALUES ('legacy-1', 'tool.succeeded', 'test', '旧提交', '2026-08-23 12:00:00.000000', '{}')",
    "INSERT INTO world_commit_scopes (commit_id, scope, sequence) VALUES ('legacy-1', 'qq:group:1', 1)",
    "INSERT INTO world_commit_bases (commit_id, scope, sequence) VALUES ('legacy-1', 'qq:group:1', 0)",
)


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


def test_sqlalchemy_journal_delta_advances_only_the_requested_partitions(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", page_size=2)
        await journal.initialize()
        await journal.append_commits(
            (
                WorldCommitInput("c-1", "tool.succeeded", "test", "第一项", frozenset({"a"}), WorldFrontier()),
                WorldCommitInput("c-2", "tool.succeeded", "test", "第二项", frozenset({"b"}), WorldFrontier()),
                WorldCommitInput("c-3", "tool.succeeded", "test", "第三项", frozenset({"a", "b"}), WorldFrontier()),
                WorldCommitInput("c-4", "tool.succeeded", "test", "第四项", frozenset({"a"}), WorldFrontier()),
            )
        )

        head = await journal.head(frozenset({"a", "b"}))
        settled = await journal.delta(head, frozenset({"a", "b"}))
        assert settled.commits == () and settled.has_more is False and settled.end == head

        first = await journal.delta(WorldFrontier(), frozenset({"a", "b"}))
        assert [commit.commit_id for commit in first.commits] == ["c-1", "c-2"]
        assert dict(first.end.positions) == {"a": 1, "b": 1} and first.has_more is True

        second = await journal.delta(first.end, frozenset({"a", "b"}))
        assert [commit.commit_id for commit in second.commits] == ["c-3", "c-4"]
        assert dict(second.end.positions) == {"a": 3, "b": 2} and second.has_more is False

        only_b = await journal.delta(WorldFrontier(), frozenset({"b"}))
        assert [commit.commit_id for commit in only_b.commits] == ["c-2", "c-3"]
        assert dict(only_b.end.positions) == {"b": 2}
        await journal.close()

    asyncio.run(scenario())


def test_sqlalchemy_journal_delta_cost_follows_the_page_not_the_world(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", page_size=8)
        await journal.initialize()
        scopes = frozenset({"scope-a", "scope-b", "scope-c"})
        await journal.append_commits(
            tuple(
                WorldCommitInput(
                    f"c-{index:03d}",
                    "tool.succeeded",
                    "test",
                    f"第 {index} 项",
                    frozenset({f"scope-{chr(ord('a') + index % 3)}"}),
                    WorldFrontier(),
                )
                for index in range(_BULK_COMMIT_COUNT)
            )
        )
        head = await journal.head(scopes)
        statements: list[str] = []

        def record(
            connection: object,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            statements.append(statement)

        event.listen(Engine, "before_cursor_execute", record)
        try:
            settled = await journal.delta(head, scopes)
            settled_statements = len(statements)
            statements.clear()
            page = await journal.delta(WorldFrontier(), scopes)
            page_statements = len(statements)
        finally:
            event.remove(Engine, "before_cursor_execute", record)

        assert settled.commits == () and settled.has_more is False and settled.end == head
        assert page_statements > settled_statements
        assert [commit.commit_id for commit in page.commits] == [f"c-{index:03d}" for index in range(8)]
        assert page.has_more is True
        assert settled_statements <= _DELTA_STATEMENT_BUDGET and page_statements <= _DELTA_STATEMENT_BUDGET
        await journal.close()

    asyncio.run(scenario())


def test_sqlalchemy_journal_migrates_existing_world_to_partition_indexes(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "world.sqlite3"
        with closing(sqlite3.connect(path)) as connection:
            for statement in _V1_SCHEMA:
                connection.execute(statement)
            connection.commit()

        journal = SqlAlchemyWorldJournal(path)
        await journal.initialize()
        legacy = await journal.commit("legacy-1")
        page = await journal.delta(WorldFrontier(), frozenset({"qq:group:1"}))

        assert legacy is not None and legacy.summary == "旧提交"
        assert legacy.cursor == 1 and legacy.recorded_at is not None
        assert legacy.recorded_at.tzinfo is not None
        assert [commit.commit_id for commit in page.commits] == ["legacy-1"]
        assert page.end.sequence("qq:group:1") == 1
        await journal.close()

        with closing(sqlite3.connect(path)) as connection:
            version = connection.execute("SELECT version FROM schema_meta").fetchone()
            indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert version == (TARGET_VERSION,)
        assert "world_commit_scope_partition" in indexes

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
                    frozenset({"aurora:run/a"}),
                    WorldFrontier(),
                    {"tree_id": "a", "tool": "x"},
                    later,
                ),
                WorldCommitInput(
                    "a-2",
                    "tool.succeeded",
                    "engine",
                    "完成",
                    frozenset({"aurora:run/a"}),
                    WorldFrontier(),
                    {"tree_id": "a", "tool": "x"},
                    later,
                ),
                WorldCommitInput(
                    "b-1",
                    "tool.requested",
                    "engine",
                    "请求",
                    frozenset({"aurora:run/b"}),
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


def test_sqlalchemy_journal_reports_cursor_and_recently_active_scopes(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        await journal.append_commits(
            (
                WorldCommitInput(
                    "new-1",
                    "environment.message",
                    "qq",
                    "新消息",
                    frozenset({"qq:new"}),
                    WorldFrontier(),
                    {},
                    now,
                ),
                WorldCommitInput(
                    "old-1",
                    "environment.message",
                    "qq",
                    "旧消息",
                    frozenset({"qq:old"}),
                    WorldFrontier(),
                    {},
                    now - timedelta(hours=2),
                ),
            )
        )

        assert await journal.cursor() == _RECENT_COMMIT_COUNT
        assert await journal.active_scopes(now - timedelta(hours=1)) == ("qq:new",)
        await journal.close()

    asyncio.run(scenario())


def test_sqlalchemy_journal_streams_continuous_events_by_global_cursor(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        await journal.append_commits(
            (
                WorldCommitInput(
                    "c-1", "engine.tree.started", "engine", "第一项", frozenset({"aurora:run/a"}), WorldFrontier()
                ),
                WorldCommitInput(
                    "c-2", "tool.requested", "engine", "第二项", frozenset({"aurora:run/a"}), WorldFrontier()
                ),
                WorldCommitInput(
                    "c-3", "environment.message", "qq", "第三项", frozenset({"qq:group"}), WorldFrontier()
                ),
            )
        )

        first = await journal.stream(0, 2)
        second = await journal.stream(first.end, 10)
        empty = await journal.stream(second.end, 10)

        assert first.after == 0 and first.end == _FIRST_PAGE_END and first.has_more is True
        assert [commit.commit_id for commit in first.commits] == ["c-1", "c-2"]
        assert [commit.commit_id for commit in second.commits] == ["c-3"]
        assert second.has_more is False
        assert empty.commits == () and empty.after == empty.end == _COMMIT_COUNT
        with pytest.raises(ValueError, match="after"):
            await journal.stream(-1, 10)
        with pytest.raises(ValueError, match="limit"):
            await journal.stream(0, 0)
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
