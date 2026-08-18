"""本地终端的异步读行、中文渲染与停止协调。"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import clear as clear_terminal

from src.console.models import TerminalControl

if TYPE_CHECKING:
    from collections.abc import Callable

    from prompt_toolkit.input import Input
    from prompt_toolkit.output import Output

    from src.console.models import TerminalDispatcher


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
        return await self.session.prompt_async("你> ")


class TerminalConsole:
    """只通过文本分派端口工作的本地终端。"""

    async def run(
        self,
        dispatcher: TerminalDispatcher,
        *,
        stop_event: asyncio.Event | None = None,
        readline: Callable[[str], str] | None = None,
        output: Callable[[str], None] = print,
    ) -> None:
        stop = stop_event or asyncio.Event()
        output("AuroraBot 本地终端；输入 /help 查看操作。")
        prompt_reader = _PromptReader() if readline is None else None
        terminal_context = patch_stdout(raw=True) if prompt_reader is not None else contextlib.nullcontext()
        with terminal_context:
            while not stop.is_set():
                result, stopped = await _read_input_or_stop(prompt_reader, readline, stop)
                if stopped:
                    return
                if result.closed:
                    output("")
                    stop.set()
                    return
                raw = (result.text or "").strip()
                if not raw:
                    continue
                response = await dispatcher.dispatch_terminal(raw)
                if response.control is TerminalControl.CLEAR:
                    _clear_console(prompt_reader, output)
                    continue
                if response.text is not None:
                    prefix = "Aurora! " if response.is_error else "Aurora> "
                    output(f"{prefix}{response.text}")
                if response.control is TerminalControl.SHUTDOWN:
                    stop.set()
                    return


async def _read_input_or_stop(
    prompt_reader: _PromptReader | None,
    readline: Callable[[str], str] | None,
    stop: asyncio.Event,
) -> tuple[_ReadResult, bool]:
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
        return _ReadResult(None, closed=True), True
    return read_task.result(), False


async def _read_input(
    prompt_reader: _PromptReader | None,
    readline: Callable[[str], str] | None,
) -> _ReadResult:
    try:
        if prompt_reader is not None:
            return _ReadResult(await prompt_reader.read())
        assert readline is not None
        return _ReadResult(await asyncio.to_thread(readline, "你> "))
    except (EOFError, KeyboardInterrupt, StopIteration):
        return _ReadResult(None, closed=True)


def _clear_console(prompt_reader: _PromptReader | None, output: Callable[[str], None]) -> None:
    if prompt_reader is not None:
        clear_terminal()
    else:
        output("\033[2J\033[H")
