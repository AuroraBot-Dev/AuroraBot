from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora_bot.cadence import CADENCE_SCOPE, CADENCE_TICK, Cadence, ReactiveRule
from aurora_bot.contracts import (
    MCP_EVENT_RECEIVED,
    EnvironmentEvent,
    RunActivity,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
    WorldStreamPage,
)
from aurora_bot.rhythm.rules import RuleRhythmPolicy
from tests.runtime.support import FakeLauncher

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
        if not self.pages:
            return WorldStreamPage(after, after, (), False)
        page = self.pages.pop(0)
        if len(page.commits) <= limit:
            return page
        split = after + limit
        self.pages.insert(0, WorldStreamPage(split, page.end, page.commits[limit:], page.has_more))
        return WorldStreamPage(after, split, page.commits[:limit], True)

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

    async def run_index(self, limit: int) -> tuple[RunActivity, ...]:
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


def _page(after: int, commits: tuple[WorldCommit, ...], *, end: int | None = None) -> WorldStreamPage:
    return WorldStreamPage(after, end if end is not None else after + len(commits), commits, False)


def test_cadence_evokes_one_tree_per_five_counted_commits() -> None:
    reader = FakeReader([_page(0, tuple(_commit(f"c-{i}", MCP_EVENT_RECEIVED) for i in range(1, 6)))])
    writer = FakeWriter()
    launcher = FakeLauncher()
    cadence = Cadence(
        reader,
        writer,
        policy=RuleRhythmPolicy(),
        launcher=launcher,
        agent="aurora:agent/definition/triage",
        poll_interval=0.01,
    )

    asyncio.run(cadence.evaluate_once())

    assert [request.run_id for request in launcher.requests] == [launcher.requests[0].run_id]
    assert launcher.requests[0].agent == "aurora:agent/definition/triage"
    assert cadence.status()["pending"] == 0
    assert [item.kind for item in writer.inputs].count("cadence.run_planned") == 1
    assert writer.inputs[-1].kind == "cadence.run_completed"
    assert all(item.data["decision"]["action"] == "wait" for item in writer.inputs if item.kind == "cadence.decided")


def test_cadence_ignores_engine_commits_when_counting() -> None:
    commits = (
        *(_commit(f"engine-{i}", "engine.model.completed") for i in range(1, 4)),
        _commit("external-1", MCP_EVENT_RECEIVED),
    )
    reader = FakeReader([_page(0, commits)])
    writer = FakeWriter()
    launcher = FakeLauncher()
    cadence = Cadence(reader, writer, policy=RuleRhythmPolicy(), launcher=launcher)

    asyncio.run(cadence.evaluate_once())

    assert launcher.requests == []
    assert cadence.status()["pending"] == 1


def test_cadence_tick_and_launch_failure_are_recorded() -> None:
    reader = FakeReader(
        [_page(0, tuple(_commit(f"c-{i}", MCP_EVENT_RECEIVED) for i in range(1, 6)))],
        cursor=0,
    )
    writer = FakeWriter()
    launcher = FakeLauncher(failure=RuntimeError("launcher broken"))
    cadence = Cadence(reader, writer, policy=RuleRhythmPolicy(max_idle_seconds=1), launcher=launcher)

    async def scenario() -> None:
        await cadence._submit_tick()
        await cadence.evaluate_once()

    asyncio.run(scenario())

    kinds = [item.kind for item in writer.inputs]
    assert kinds[0] == CADENCE_TICK
    assert kinds[-2:] == ["cadence.run_planned", "cadence.run_failed"]
    assert writer.inputs[0].scopes == frozenset({CADENCE_SCOPE})


def test_cadence_rejects_invalid_bounds() -> None:
    reader = FakeReader([])
    writer = FakeWriter()

    with pytest.raises(ValueError, match="poll_interval"):
        Cadence(reader, writer, policy=RuleRhythmPolicy(), poll_interval=0)


def test_reactive_rule_launches_with_disclosed_frontier_memory_scope_and_exact_cursor() -> None:
    commit = WorldCommit(
        "mcp:qq:event:1",
        MCP_EVENT_RECEIVED,
        "mcp:org.aurora.qq",
        "QQ 私聊收到 Aurore 的消息: 在吗",
        datetime.now(UTC),
        {"qq:private:42": 7, "org.aurora.qq:world": 11},
        WorldFrontier(),
        {"event_kind": "qq.message.private", "data": {"user_id": "42"}},
    )
    reader = FakeReader([_page(0, (commit,), end=1)], cursor=99)
    writer = FakeWriter()
    launcher = FakeLauncher()
    cadence = Cadence(
        reader,
        writer,
        policy=RuleRhythmPolicy(),
        launcher=launcher,
        reactive_rules=(ReactiveRule("mcp:org.aurora.qq", "qq.message.private", "aurora:agent/definition/chat"),),
    )

    asyncio.run(cadence.evaluate_once())

    assert len(launcher.requests) == 1
    request = launcher.requests[0]
    assert request.agent == "aurora:agent/definition/chat"
    assert request.caused_by == commit.commit_id
    assert request.frontier == WorldFrontier(commit.scopes)
    assert request.memory_scopes == frozenset(commit.scopes)
    assert "在吗" in request.message
    assert '"user_id":"42"' in request.message
    assert cadence.status()["cursor"] == 1
    assert cadence.status()["pending"] == 0


def test_group_reactive_rule_requires_configured_name() -> None:
    commits = tuple(
        WorldCommit(
            f"group-{index}",
            MCP_EVENT_RECEIVED,
            "mcp:org.aurora.qq",
            summary,
            datetime.now(UTC),
            {"qq:group:1": index},
            WorldFrontier(),
            {"event_kind": "qq.message.group", "data": {"group_id": "1"}},
        )
        for index, summary in enumerate(("QQ 群收到消息: 大家好", "QQ 群收到消息: 小光在吗"), start=1)
    )
    reader = FakeReader([_page(0, commits)])
    launcher = FakeLauncher()
    cadence = Cadence(
        reader,
        FakeWriter(),
        policy=RuleRhythmPolicy(),
        launcher=launcher,
        reactive_rules=(
            ReactiveRule("mcp:org.aurora.qq", "qq.message.group", "aurora:agent/definition/chat", ("小光", "夜曦光")),
        ),
    )

    asyncio.run(cadence.evaluate_once())

    assert len(launcher.requests) == 1
    assert launcher.requests[0].caused_by == "group-2"
    assert cadence.status()["pending"] == 1
