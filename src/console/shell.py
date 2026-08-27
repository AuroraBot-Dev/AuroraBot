"""本地终端的异步读行、中文渲染与停止协调。"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import clear as clear_terminal

from src.console.models import TerminalControl
from src.contracts import CONSOLE_INPUT, CONSOLE_SCOPE, WorldFrontier, WorldWriter
from src.utils import get_logger

_logger = get_logger(__name__)

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
        return await self.session.prompt_async("You> ")


class TerminalConsole:
    """本地终端；所有非空输入先进入世界线，再通过文本分派端口处理。"""

    def __init__(self, world: WorldWriter | None = None) -> None:
        self._world = world

    async def run(
        self,
        dispatcher: TerminalDispatcher,
        *,
        stop_event: asyncio.Event | None = None,
        readline: Callable[[str], str] | None = None,
        output: Callable[[str], None] = print,
    ) -> None:
        stop = stop_event or asyncio.Event()
        _logger.info("本地终端启动")
        output("AuroraBot 本地终端；输入 /help 查看操作。")
        prompt_reader = _PromptReader() if readline is None else None
        terminal_context = patch_stdout(raw=True) if prompt_reader is not None else contextlib.nullcontext()
        with terminal_context:
            while not stop.is_set():
                result, stopped = await _read_input_or_stop(prompt_reader, readline, stop)
                if stopped:
                    _logger.info("本地终端收到停止请求")
                    return
                if result.closed:
                    _logger.info("本地终端输入已关闭")
                    output("")
                    stop.set()
                    return
                raw = (result.text or "").strip()
                if not raw:
                    continue
                _logger.debug("本地终端收到非空输入 input_type={}", "operation" if raw.startswith("/") else "message")
                if self._world is not None:
                    await self._world.append_commit(
                        commit_id=f"console:{uuid4().hex}",
                        kind=CONSOLE_INPUT,
                        source="console",
                        summary=raw,
                        scopes=frozenset({CONSOLE_SCOPE}),
                        based_on=WorldFrontier(),
                        data={"text": raw},
                        occurred_at=datetime.now(UTC),
                    )
                response = await dispatcher.dispatch_terminal(raw)
                _logger.debug("本地终端分派完成 is_error={} control={}", response.is_error, response.control.value)
                if response.control is TerminalControl.CLEAR:
                    _clear_console(prompt_reader, output)
                    continue
                if response.text is not None:
                    prefix = "Aurora! " if response.is_error else "Bot> "
                    output(f"{prefix}{response.text}")
                if response.control is TerminalControl.SHUTDOWN:
                    _logger.info("本地终端请求进程关闭")
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
        return _ReadResult(await asyncio.to_thread(readline, "You> "))
    except (EOFError, KeyboardInterrupt, StopIteration):
        return _ReadResult(None, closed=True)


def _clear_console(prompt_reader: _PromptReader | None, output: Callable[[str], None]) -> None:
    if prompt_reader is not None:
        clear_terminal()
    else:
        output("\033[2J\033[H")
