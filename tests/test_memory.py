from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from src.contracts import WorldCommitInput, WorldFrontier
from src.memory import Memory
from src.utils.patterns import NamePatternError
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path


def test_memory_returns_recent_active_scopes_with_latest_details(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        await journal.append_commits(
            (
                WorldCommitInput(
                    "recent-1",
                    "environment.message",
                    "qq",
                    "最近消息",
                    frozenset({"qq:group"}),
                    WorldFrontier(),
                    {"message_id": 1},
                    now - timedelta(minutes=5),
                ),
                WorldCommitInput(
                    "recent-2",
                    "tool.succeeded",
                    "engine",
                    "最近完成",
                    frozenset({"aurora:tree:tree"}),
                    WorldFrontier(),
                    {"detail": "ok"},
                    now - timedelta(minutes=2),
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
        snapshot = await Memory(journal, commits_per_scope=1).recall(now=now)
        rendered = Memory.render(snapshot)
        await journal.close()

        assert [scope.scope for scope in snapshot.scopes] == ["aurora:tree:tree", "qq:group"]
        assert [scope.commits[0].commit_id for scope in snapshot.scopes] == ["recent-2", "recent-1"]
        assert "最近完成" in rendered
        assert '"detail":"ok"' in rendered

    asyncio.run(scenario())


def test_memory_rejects_non_positive_window_and_limits() -> None:
    class FakeReader:
        async def active_scopes(self, since: datetime) -> tuple[str, ...]:
            raise NotImplementedError

    with pytest.raises(ValueError, match="window"):
        Memory(FakeReader(), window=timedelta(0))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="commits_per_scope"):
        Memory(FakeReader(), commits_per_scope=0)  # type: ignore[arg-type]


def test_memory_filters_scopes_with_include_and_exclude_patterns(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        await journal.append_commits(
            (
                WorldCommitInput(
                    "group-1",
                    "environment.message",
                    "qq",
                    "群消息",
                    frozenset({"qq:group"}),
                    WorldFrontier(),
                    {},
                    now - timedelta(minutes=5),
                ),
                WorldCommitInput(
                    "secret-1",
                    "environment.message",
                    "qq",
                    "私聊",
                    frozenset({"qq:secret"}),
                    WorldFrontier(),
                    {},
                    now - timedelta(minutes=4),
                ),
                WorldCommitInput(
                    "run-1",
                    "tool.succeeded",
                    "engine",
                    "运行因果",
                    frozenset({"aurora:tree:tree"}),
                    WorldFrontier(),
                    {},
                    now - timedelta(minutes=3),
                ),
            )
        )
        memory = Memory(journal, commits_per_scope=1, scope_include=("qq:*",), scope_exclude=("qq:secret",))
        snapshot = await memory.recall(now=now)
        await journal.close()

        assert [scope.scope for scope in snapshot.scopes] == ["qq:group"]

    asyncio.run(scenario())


def test_memory_include_negation_reinjects_an_excluded_scope(tmp_path: Path) -> None:
    async def scenario() -> None:
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        await journal.append_commits(
            (
                WorldCommitInput(
                    "group-1",
                    "environment.message",
                    "qq",
                    "群消息",
                    frozenset({"qq:group"}),
                    WorldFrontier(),
                    {},
                    now - timedelta(minutes=5),
                ),
                WorldCommitInput(
                    "run-1",
                    "tool.succeeded",
                    "engine",
                    "运行因果",
                    frozenset({"aurora:tree:tree"}),
                    WorldFrontier(),
                    {},
                    now - timedelta(minutes=3),
                ),
            )
        )
        memory = Memory(journal, commits_per_scope=1, scope_include=("**", "!aurora:tree:**"))
        snapshot = await memory.recall(now=now)
        await journal.close()

        assert [scope.scope for scope in snapshot.scopes] == ["qq:group"]

    asyncio.run(scenario())


def test_memory_rejects_invalid_scope_patterns() -> None:
    class FakeReader:
        async def active_scopes(self, since: datetime) -> tuple[str, ...]:
            raise NotImplementedError

    with pytest.raises(NamePatternError):
        Memory(FakeReader(), scope_include=("qq:[",))  # type: ignore[arg-type]
