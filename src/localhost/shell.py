"""Interactive Console adapter for the shared runtime input router."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.localhost.command_types import CommandControl, InputOrigin, RuntimeInput
from src.utils.log_utils import configure_console_logging, get_logger

logger = get_logger("aurora.localhost.console")

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.localhost.runtime import AuroraRuntime


@dataclass(frozen=True, slots=True)
class _ReadResult:
    text: str | None
    closed: bool = False


async def run_console(
    runtime: AuroraRuntime,
    *,
    stop_event: asyncio.Event | None = None,
    readline: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> None:
    """Route Console input without owning the shared Runtime lifecycle."""
    stop = stop_event or asyncio.Event()
    configure_console_logging(enabled=False)
    output("AuroraBot local console; 输入 /help 查看命令。")
    reads: asyncio.Queue[_ReadResult] = asyncio.Queue()
    reader_closed = threading.Event()
    _start_reader(readline, reads, reader_closed)
    display = asyncio.create_task(_display_messages(runtime, output), name="aurora-console-output")
    logger.info("developer console started")
    try:
        while not stop.is_set():
            read_task = asyncio.create_task(reads.get(), name="aurora-console-read")
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
                runtime.request_shutdown()
                return
            raw = (result.text or "").strip()
            if not raw:
                continue
            routed = await runtime.route_input(
                RuntimeInput(
                    text=raw,
                    origin=InputOrigin.CONSOLE,
                    session_id="local:console",
                    source_app="localhost.console",
                    source_instance="default",
                    reply_capability="org.aurora.console.send_message",
                )
            )
            if routed.text is not None:
                output(routed.text)
            if routed.control is CommandControl.SHUTDOWN_PROCESS:
                runtime.request_shutdown()
                return
    finally:
        reader_closed.set()
        display.cancel()
        await asyncio.gather(display, return_exceptions=True)
        logger.info("developer console stopped")


def _start_reader(
    readline: Callable[[str], str],
    queue: asyncio.Queue[_ReadResult],
    closed: threading.Event,
) -> None:
    loop = asyncio.get_running_loop()

    def worker() -> None:
        while not closed.is_set():
            try:
                result = _ReadResult(readline("Aurora> "))
            except (EOFError, KeyboardInterrupt, StopIteration):
                result = _ReadResult(None, closed=True)
            if closed.is_set():
                return
            try:
                loop.call_soon_threadsafe(queue.put_nowait, result)
            except RuntimeError:
                return
            if result.closed:
                return

    threading.Thread(target=worker, name="aurora-console-reader", daemon=True).start()


async def _display_messages(runtime: AuroraRuntime, output: Callable[[str], None]) -> None:
    while True:
        output(f"Bot> {await runtime.next_console_message()}")
