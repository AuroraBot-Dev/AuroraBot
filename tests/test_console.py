from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aurora import load_config
from src.console import TerminalConsole, TerminalControl, TerminalResponse
from src.contracts import (
    FRONT_BINDINGS,
    ChatMessage,
    EnvironmentEvent,
    Front,
    FrontContext,
    ModelRequest,
    WorldCommit,
    WorldCommitInput,
    WorldFrontier,
)
from src.contracts.pkgs.world import WorldJournal
from src.runtime import run_runtime

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


class FakeWorld:
    def __init__(self) -> None:
        self.commits: list[WorldCommit] = []

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
        commit = WorldCommit(
            commit_id,
            kind,
            source,
            summary,
            occurred_at or datetime.now(UTC),
            {scope: 1 for scope in scopes},
            based_on,
            dict(data),
        )
        self.commits.append(commit)
        return commit

    async def append_event(self, event: EnvironmentEvent) -> WorldCommit:
        raise NotImplementedError

    async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]:
        raise NotImplementedError


@dataclass(slots=True)
class FakeDispatcher:
    inputs: list[str] = field(default_factory=list)

    async def dispatch_terminal(self, text: str) -> TerminalResponse:
        self.inputs.append(text)
        if text == "/clear":
            return TerminalResponse(control=TerminalControl.CLEAR)
        if text == "/exit":
            return TerminalResponse("正在停止。", TerminalControl.SHUTDOWN)
        return TerminalResponse(f"收到：{text}")


@dataclass(slots=True)
class FakeModel:
    requests: list[ModelRequest] = field(default_factory=list)

    def validate_endpoint(self, endpoint_id: str) -> None:
        del endpoint_id

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        return ChatMessage.assistant("全链路完成")


def _readline(values: list[str]) -> Callable[[str], str]:
    pending = deque(values)

    def read(_prompt: str) -> str:
        if not pending:
            raise EOFError
        return pending.popleft()

    return read


def test_terminal_console_routes_text_renders_controls_and_stops() -> None:
    dispatcher = FakeDispatcher()
    output: list[str] = []
    stop = asyncio.Event()

    asyncio.run(
        TerminalConsole().run(
            dispatcher,
            stop_event=stop,
            readline=_readline(["", "你好", "/clear", "/exit"]),
            output=output.append,
        )
    )

    assert dispatcher.inputs == ["你好", "/clear", "/exit"]
    assert output[0] == "AuroraBot 本地终端；输入 /help 查看本地命令。"
    assert "Bot> 收到：你好" in output
    assert "\033[2J\033[H" in output
    assert stop.is_set()


def test_terminal_console_records_every_non_empty_input_to_worldline() -> None:
    dispatcher = FakeDispatcher()
    world = FakeWorld()
    output: list[str] = []
    stop = asyncio.Event()

    asyncio.run(
        TerminalConsole(world).run(
            dispatcher,
            stop_event=stop,
            readline=_readline(["请处理", "/status", "/exit"]),
            output=output.append,
        )
    )

    assert [commit.summary for commit in world.commits] == ["请处理", "/status", "/exit"]
    assert {scope for commit in world.commits for scope in commit.scopes} == {"aurora:world/console"}
    assert {commit.kind for commit in world.commits} == {"console.input"}
    assert dispatcher.inputs == ["请处理", "/status", "/exit"]


def test_project_console_runs_message_tree_and_local_commands(configured_project: Path) -> None:
    output: list[str] = []
    model = FakeModel()
    stop = asyncio.Event()

    runtime = asyncio.run(
        run_runtime(
            load_config(configured_project),
            model,
            stop_event=stop,
            readline=_readline(["请处理", "/help", "/quit"]),
            output=output.append,
        )
    )

    assert len(model.requests) == 1
    assert model.requests[0].messages[1].content == "请处理"
    assert runtime.runtime_status()["trees"]["completed"] == 1
    assert "Bot> 全链路完成" in output
    assert "Bot> 本地命令：/help /clear /quit" in output
    assert stop.is_set()


def test_project_headless_waits_only_for_shared_stop_event(configured_project: Path) -> None:
    stop = asyncio.Event()
    stop.set()
    output: list[str] = []

    runtime = asyncio.run(
        run_runtime(load_config(configured_project), FakeModel(), headless=True, stop_event=stop, output=output.append)
    )

    assert runtime.runtime_status()["tree_count"] == 0
    assert output == []


def test_headless_runs_contributed_non_interactive_front(configured_project: Path) -> None:
    ran: list[str] = []

    async def front(stop: asyncio.Event) -> None:
        ran.append("front")
        stop.set()

    def bind(_context: object) -> Front:
        return Front(front, interactive=False)

    stop = asyncio.Event()
    asyncio.run(
        run_runtime(
            load_config(configured_project),
            FakeModel(),
            headless=True,
            stop_event=stop,
            output=lambda _message: None,
            contributions=((FRONT_BINDINGS, bind),),
        )
    )

    assert ran == ["front"]


def test_headless_skips_interactive_front(configured_project: Path) -> None:
    ran: list[str] = []

    async def front(stop: asyncio.Event) -> None:
        ran.append("front")

    def bind(_context: object) -> Front:
        return Front(front, interactive=True)

    stop = asyncio.Event()
    stop.set()
    asyncio.run(
        run_runtime(
            load_config(configured_project),
            FakeModel(),
            headless=True,
            stop_event=stop,
            output=lambda _message: None,
            contributions=((FRONT_BINDINGS, bind),),
        )
    )

    assert ran == []


def test_contributed_front_reads_capabilities_by_declaration(configured_project: Path) -> None:
    resolved: list[object] = []

    def bind(context: FrontContext) -> Front:
        resolved.append(context.get(WorldJournal))

        async def front(stop: asyncio.Event) -> None:
            stop.set()

        return Front(front, interactive=False)

    stop = asyncio.Event()
    asyncio.run(
        run_runtime(
            load_config(configured_project),
            FakeModel(),
            headless=True,
            stop_event=stop,
            output=lambda _message: None,
            contributions=((FRONT_BINDINGS, bind),),
        )
    )

    assert len(resolved) == 1
