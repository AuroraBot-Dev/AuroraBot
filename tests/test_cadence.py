from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from src.cadence import CADENCE_SCOPE, CADENCE_TICK, Cadence
from src.contracts import (
    EnvironmentEvent,
    TreeActivity,
    TreeLaunchRequest,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
    WorldStreamPage,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _commit(commit_id: str, kind: str, *, sequence: int = 1) -> WorldCommit:
    return WorldCommit(
        commit_id,
        kind,
        "test",
        commit_id,
        datetime.now(UTC),
        {"scope": sequence},
        WorldFrontier(),
        {"commit_id": commit_id},
    )


class FakeReader:
    def __init__(self, pages: list[WorldStreamPage], *, cursor: int = 0) -> None:
        self.pages = pages
        self.cursor_value = cursor
        self.calls: list[tuple[int, int]] = []

    async def cursor(self) -> int:
        return self.cursor_value

    async def stream(self, after: int, limit: int) -> WorldStreamPage:
        self.calls.append((after, limit))
        return self.pages.pop(0) if self.pages else WorldStreamPage(after, after, (), False)

    async def head(self, scopes: frozenset[str]) -> WorldFrontier:
        return WorldFrontier()

    async def delta(self, start: WorldFrontier, scopes: frozenset[str]) -> WorldDeltaPage:
        raise NotImplementedError

    async def active_scopes(self, since: datetime) -> tuple[str, ...]:
        raise NotImplementedError

    async def commit(self, commit_id: str) -> WorldCommit | None:
        raise NotImplementedError

    async def commits(self, scope: str, after: int, limit: int) -> tuple[WorldCommit, ...]:
        raise NotImplementedError

    async def tree_index(self, limit: int) -> tuple[TreeActivity, ...]:
        raise NotImplementedError


class FakeWriter:
    def __init__(self) -> None:
        self.inputs: list[WorldCommitInput] = []

    async def append_commit(
        self,
        *,
        commit_id: str,
        kind: str,
        source: str,
        summary: str,
        scopes: frozenset[str],
        based_on: WorldFrontier,
        data: Mapping[str, object],
        occurred_at: datetime | None = None,
    ) -> WorldCommit:
        self.inputs.append(WorldCommitInput(commit_id, kind, source, summary, scopes, based_on, data, occurred_at))
        return WorldCommit(
            commit_id,
            kind,
            source,
            summary,
            occurred_at or datetime.now(UTC),
            {scope: 1 for scope in scopes},
            based_on,
            data,
        )

    async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]:
        raise NotImplementedError

    async def append_event(self, event: EnvironmentEvent) -> WorldCommit:
        raise NotImplementedError


@dataclass(slots=True)
class FakeLauncher:
    requests: list[TreeLaunchRequest] = field(default_factory=list)
    failure: Exception | None = None

    async def launch_tree(self, request: TreeLaunchRequest) -> dict[str, object]:
        if self.failure is not None:
            raise self.failure
        self.requests.append(request)
        return {"tree_id": request.tree_id, "status": "running"}


def _page(after: int, commits: tuple[WorldCommit, ...], *, end: int | None = None) -> WorldStreamPage:
    return WorldStreamPage(after, end if end is not None else after + len(commits), commits, False)


def test_cadence_evokes_one_tree_per_five_counted_commits() -> None:
    reader = FakeReader([_page(0, tuple(_commit(f"c-{i}", "environment.message") for i in range(1, 6)))])
    writer = FakeWriter()
    launcher = FakeLauncher()
    cadence = Cadence(reader, writer, launcher=launcher, agent="builtin.triage", poll_interval=0.01)

    asyncio.run(cadence.evaluate_once())

    assert [request.tree_id for request in launcher.requests] == [launcher.requests[0].tree_id]
    assert launcher.requests[0].agent == "builtin.triage"
    assert cadence.status()["pending"] == 0
    assert [item.kind for item in writer.inputs] == ["cadence.tree_planned"]


def test_cadence_ignores_engine_commits_when_counting() -> None:
    commits = (
        *(_commit(f"engine-{i}", "engine.model.completed") for i in range(1, 4)),
        _commit("external-1", "environment.message"),
    )
    reader = FakeReader([_page(0, commits)])
    writer = FakeWriter()
    launcher = FakeLauncher()
    cadence = Cadence(reader, writer, launcher=launcher)

    asyncio.run(cadence.evaluate_once())

    assert launcher.requests == []
    assert cadence.status()["pending"] == 1


def test_cadence_tick_and_launch_failure_are_recorded() -> None:
    reader = FakeReader(
        [_page(0, tuple(_commit(f"c-{i}", "environment.message") for i in range(1, 6)))],
        cursor=0,
    )
    writer = FakeWriter()
    launcher = FakeLauncher(failure=RuntimeError("launcher broken"))
    cadence = Cadence(reader, writer, launcher=launcher, tick_every=timedelta(seconds=1))

    async def scenario() -> None:
        await cadence._submit_tick()
        await cadence.evaluate_once()

    asyncio.run(scenario())

    assert [item.kind for item in writer.inputs] == [CADENCE_TICK, "cadence.tree_planned", "cadence.tree_failed"]
    assert writer.inputs[0].scopes == frozenset({CADENCE_SCOPE})


def test_cadence_rejects_invalid_bounds() -> None:
    reader = FakeReader([])
    writer = FakeWriter()

    with pytest.raises(ValueError, match="evoke_every"):
        Cadence(reader, writer, evoke_every=0)
    with pytest.raises(ValueError, match="tick_every"):
        Cadence(reader, writer, tick_every=timedelta(0))
    with pytest.raises(ValueError, match="poll_interval"):
        Cadence(reader, writer, poll_interval=0)
