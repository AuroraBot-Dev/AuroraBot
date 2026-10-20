from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from aurorabot.contracts import ScopeCatalog, ScopeDeclaration, ScopeKind, WorldCommitInput, WorldFrontier
from aurorabot.contracts.memory import MemoryRequest
from aurorabot.memory import Memory
from aurorabot.memory_model.rules import RuleMemoryPolicy
from aurorabot.utils.patterns import NamePatternError
from aurorabot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path


def test_memory_returns_recent_active_scopes_with_latest_details(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: now)
        await journal.initialize()
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
                    frozenset({"aurora:run/tree"}),
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
        snapshot = await Memory(journal, policy=RuleMemoryPolicy(), commits_per_scope=1).recall(
            MemoryRequest(observed_at=now)
        )
        await journal.close()

        assert [scope.scope for scope in snapshot.scopes] == ["aurora:run/tree", "qq:group"]
        assert [scope.commits[0].commit_id for scope in snapshot.scopes] == ["recent-2", "recent-1"]
        assert snapshot.scopes[0].commits[0].summary == "最近完成"
        assert snapshot.scopes[0].commits[0].data == {"detail": "ok"}

    asyncio.run(scenario())


def test_memory_rejects_non_positive_window_and_limits() -> None:
    class FakeReader:
        async def active_scopes(self, since: datetime) -> tuple[str, ...]:
            raise NotImplementedError

    with pytest.raises(ValueError, match="window"):
        Memory(FakeReader(), policy=RuleMemoryPolicy(), window=timedelta(0))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="commits_per_scope"):
        Memory(FakeReader(), policy=RuleMemoryPolicy(), commits_per_scope=0)  # type: ignore[arg-type]


def test_memory_filters_scopes_with_include_and_exclude_patterns(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: now)
        await journal.initialize()
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
                    frozenset({"aurora:run/tree"}),
                    WorldFrontier(),
                    {},
                    now - timedelta(minutes=3),
                ),
            )
        )
        memory = Memory(
            journal,
            policy=RuleMemoryPolicy(),
            commits_per_scope=1,
            scope_include=("qq:*",),
            scope_exclude=("qq:secret",),
        )
        snapshot = await memory.recall(MemoryRequest(observed_at=now))
        await journal.close()

        assert [scope.scope for scope in snapshot.scopes] == ["qq:group"]

    asyncio.run(scenario())


def test_memory_include_negation_reinjects_an_excluded_scope(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: now)
        await journal.initialize()
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
                    frozenset({"aurora:run/tree"}),
                    WorldFrontier(),
                    {},
                    now - timedelta(minutes=3),
                ),
            )
        )
        memory = Memory(journal, policy=RuleMemoryPolicy(), commits_per_scope=1, scope_include=("**", "!aurora:run/**"))
        snapshot = await memory.recall(MemoryRequest(observed_at=now))
        await journal.close()

        assert [scope.scope for scope in snapshot.scopes] == ["qq:group"]

    asyncio.run(scenario())


def test_memory_rejects_invalid_scope_patterns() -> None:
    class FakeReader:
        async def active_scopes(self, since: datetime) -> tuple[str, ...]:
            raise NotImplementedError

    with pytest.raises(NamePatternError):
        Memory(FakeReader(), policy=RuleMemoryPolicy(), scope_include=("qq:[",))  # type: ignore[arg-type]


_CATALOG = ScopeCatalog(
    (
        ScopeDeclaration("aurora:world/cadence", ScopeKind.RESOURCE, "节律决策"),
        ScopeDeclaration("aurora:run/*", ScopeKind.RUN, "一次运行的因果台账"),
    )
)


async def _two_scope_journal(tmp_path: Path, now: datetime) -> SqlAlchemyWorldJournal:
    journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: now)
    await journal.initialize()
    await journal.append_commits(
        (
            WorldCommitInput(
                "cadence-1",
                "cadence.tree_planned",
                "cadence",
                "节律决策",
                frozenset({"aurora:world/cadence"}),
                WorldFrontier(),
                {},
                now - timedelta(minutes=5),
            ),
            WorldCommitInput(
                "run-1",
                "tool.succeeded",
                "engine",
                "运行因果",
                frozenset({"aurora:run/tree"}),
                WorldFrontier(),
                {},
                now - timedelta(minutes=3),
            ),
            WorldCommitInput(
                "other-1",
                "environment.message",
                "qq",
                "群消息",
                frozenset({"qq:group"}),
                WorldFrontier(),
                {},
                now - timedelta(minutes=2),
            ),
        )
    )
    return journal


def test_memory_excludes_run_domains_declared_by_the_registry(tmp_path: Path) -> None:
    """运行台账域默认不进入记忆，不必再靠手写排除模式。"""

    async def scenario() -> None:
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        journal = await _two_scope_journal(tmp_path, now)
        memory = Memory(journal, policy=RuleMemoryPolicy(), commits_per_scope=1, catalog=_CATALOG)
        snapshot = await memory.recall(MemoryRequest(observed_at=now))
        await journal.close()

        assert [scope.scope for scope in snapshot.scopes] == ["qq:group", "aurora:world/cadence"]

    asyncio.run(scenario())


def test_memory_keeps_undeclared_scopes(tmp_path: Path) -> None:
    """缺一条声明不该丢掉真实世界内容：未声明的域一律保留。"""

    async def scenario() -> None:
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        journal = await _two_scope_journal(tmp_path, now)
        memory = Memory(journal, policy=RuleMemoryPolicy(), commits_per_scope=1, catalog=ScopeCatalog(()))
        snapshot = await memory.recall(MemoryRequest(observed_at=now))
        await journal.close()

        assert [scope.scope for scope in snapshot.scopes] == ["qq:group", "aurora:run/tree", "aurora:world/cadence"]

    asyncio.run(scenario())


def test_memory_can_opt_into_run_domains(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
        journal = await _two_scope_journal(tmp_path, now)
        memory = Memory(
            journal, policy=RuleMemoryPolicy(), commits_per_scope=1, catalog=_CATALOG, include_run_scopes=True
        )
        snapshot = await memory.recall(MemoryRequest(observed_at=now))
        await journal.close()

        assert [scope.scope for scope in snapshot.scopes] == ["qq:group", "aurora:run/tree", "aurora:world/cadence"]

    asyncio.run(scenario())
