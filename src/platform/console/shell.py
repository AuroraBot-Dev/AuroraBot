"""Interactive shell for the native Console Platform."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import clear as clear_terminal

from src.localhost.command_types import CommandControl, InputOrigin, RuntimeInput
from src.utils.log_utils import get_logger

logger = get_logger("aurora.platform.console")

if TYPE_CHECKING:
    from collections.abc import Callable

    from prompt_toolkit.input import Input
    from prompt_toolkit.output import Output

    from src.localhost.ports import ConsoleControlPort
    from src.platform.console.adapter import ConsolePlatform


@dataclass(frozen=True, slots=True)
class _ReadResult:
    text: str | None
    closed: bool = False


class _PromptReader:
    def __init__(self, *, input_stream: Input | None = None, output_stream: Output | None = None) -> None:
        self.session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),
            enable_history_search=True,
            input=input_stream,
            output=output_stream,
        )

    async def read(self) -> str:
        return await self.session.prompt_async("Aurora> ")


async def run_console(
    control: ConsoleControlPort,
    console: ConsolePlatform,
    *,
    stop_event: asyncio.Event | None = None,
    readline: Callable[[str], str] | None = None,
    output: Callable[[str], None] = print,
) -> None:
    """Route Console input without owning the shared process lifecycle."""
    stop = stop_event or asyncio.Event()
    output("AuroraBot local console; 输入 /help 查看命令。")
    prompt_reader = _PromptReader() if readline is None else None
    display = asyncio.create_task(_display_messages(console, output), name="aurora-console-output")
    read_task: asyncio.Task[_ReadResult] | None = None
    stop_task: asyncio.Task[bool] | None = None
    logger.info("developer console started")
    try:
        terminal_context = patch_stdout(raw=True) if prompt_reader is not None else contextlib.nullcontext()
        with terminal_context:
            while not stop.is_set():
                read_task = asyncio.create_task(_read_input(prompt_reader, readline), name="aurora-console-read")
                stop_task = asyncio.create_task(stop.wait(), name="aurora-console-stop")
                done, pending = await asyncio.wait({read_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                if read_task in pending:
                    await asyncio.gather(read_task, return_exceptions=True)
                if stop_task in pending:
                    await asyncio.gather(stop_task, return_exceptions=True)
                if stop_task in done and stop.is_set():
                    return
                result = read_task.result()
                if result.closed:
                    output("")
                    control.request_shutdown()
                    return
                raw = (result.text or "").strip()
                if not raw:
                    continue
                external_event_id = str(uuid4())
                routed = await control.route_input(
                    RuntimeInput(
                        text=raw,
                        origin=InputOrigin.CONSOLE,
                        session_id="local:console",
                        source_app="platform.console",
                        source_instance="default",
                        idempotency_key=external_event_id,
                        data={"channel": "local_console"},
                    )
                )
                if routed.control is CommandControl.CLEAR_CONSOLE:
                    _clear_console(prompt_reader, output)
                    continue
                if routed.text is not None:
                    output(routed.text)
                if routed.control is CommandControl.SHUTDOWN_PROCESS:
                    control.request_shutdown()
                    return
    finally:
        await _cancel_tasks(read_task, stop_task, display)
        logger.info("developer console stopped")


async def _read_input(
    prompt_reader: _PromptReader | None,
    readline: Callable[[str], str] | None,
) -> _ReadResult:
    try:
        if prompt_reader is not None:
            return _ReadResult(await prompt_reader.read())
        assert readline is not None
        return _ReadResult(await asyncio.to_thread(readline, "Aurora> "))
    except (EOFError, KeyboardInterrupt, StopIteration):
        return _ReadResult(None, closed=True)


def _clear_console(prompt_reader: _PromptReader | None, output: Callable[[str], None]) -> None:
    if prompt_reader is not None:
        clear_terminal()
    else:
        output("\033[2J\033[H")


async def _display_messages(console: ConsolePlatform, output: Callable[[str], None]) -> None:
    while True:
        output(f"Bot> {await console.next_message()}")


async def _cancel_tasks(*tasks: asyncio.Task[Any] | None) -> None:
    active = [task for task in tasks if task is not None]
    for task in active:
        task.cancel()
    await asyncio.gather(*active, return_exceptions=True)
