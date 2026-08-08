from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from src.console.shell import _display_messages, _PromptReader, run_console
from src.contracts import (
    CommandResult,
    OutputStreamItem,
    OutputStreamPage,
)
from tests.support import create_test_runtime

if TYPE_CHECKING:
    from pathlib import Path


def test_console_prompt_keeps_session_command_history() -> None:
    reader = _PromptReader(input_stream=DummyInput(), output_stream=DummyOutput())
    reader.session.history.append_string("/status")
    reader.session.history.append_string("/help")
    assert list(reader.session.history.get_strings()) == ["/status", "/help"]


def test_console_renders_model_text_and_errors_without_tool_calls() -> None:
    class Query:
        def __init__(self) -> None:
            self.polls = 0

        def output_tail_cursor(self) -> int:
            return 0

        def output_stream(self, cursor: int = 0, *, limit: int = 64) -> OutputStreamPage:  # noqa: ARG002
            self.polls += 1
            if self.polls == 1:
                return OutputStreamPage(
                    items=(
                        OutputStreamItem(
                            cursor=1,
                            activity_id="a1",
                            task_id="t",
                            session_id="s",
                            kind="model",
                            text="bot reply",
                            at="now",
                        ),
                        OutputStreamItem(
                            cursor=2,
                            activity_id="a2",
                            task_id="t",
                            session_id="s",
                            kind="error",
                            text="provider down",
                            at="now",
                        ),
                    ),
                    next_cursor=2,
                )
            return OutputStreamPage(items=(), next_cursor=cursor)

    query = Query()
    rendered: list[str] = []

    async def scenario() -> None:
        task = asyncio.create_task(_display_messages(query, rendered.append, 0.01, 0), name="render")
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    assert rendered == ["Bot> bot reply", "Bot! provider down"]
    assert query.polls > 1


def test_console_does_not_replay_history_from_output_tail() -> None:
    tail_cursor = 7

    class Query:
        def __init__(self) -> None:
            self.cursors: list[int] = []

        def output_tail_cursor(self) -> int:
            return tail_cursor

        def output_stream(self, cursor: int = 0, *, limit: int = 64) -> OutputStreamPage:  # noqa: ARG002
            self.cursors.append(cursor)
            return OutputStreamPage(items=(), next_cursor=cursor)

        async def route_input(self, request: object) -> CommandResult:  # noqa: ARG002
            return CommandResult(ok=True, text=None)

        def request_shutdown(self) -> None:
            return

    query = Query()
    rendered: list[str] = []

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            run_console(
                query,
                query,
                stop_event=stop,
                readline=lambda _prompt: "",
                output=rendered.append,
                poll_seconds=0.005,
            ),
            name="console",
        )
        await asyncio.sleep(0.03)
        stop.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
    assert query.cursors and query.cursors[0] == tail_cursor


def test_console_input_submits_conversation_and_commands(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        inputs = iter(("hello", "/pump", "/quit"))
        output: list[str] = []
        try:
            await run_console(runtime, runtime, readline=lambda _prompt: next(inputs), output=output.append)
            assert any("processed_message_ids" in line for line in output)
            assert any("admitted_task_ids" in line for line in output)
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
