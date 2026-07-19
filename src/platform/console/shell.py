"""Interactive shell for the native Console Platform."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.localhost.command_types import CommandControl, InputOrigin, RuntimeInput
from src.utils.log_utils import get_logger

logger = get_logger("aurora.platform.console")

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.localhost.ports import ConsoleControlPort
    from src.platform.console.adapter import ConsolePlatform


@dataclass(frozen=True, slots=True)
class _ReadResult:
    text: str | None
    closed: bool = False


async def run_console(
    control: ConsoleControlPort,
    console: ConsolePlatform,
    *,
    stop_event: asyncio.Event | None = None,
    readline: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> None:
    """Route Console input without owning the shared process lifecycle."""
    stop = stop_event or asyncio.Event()
    output("AuroraBot local console; 输入 /help 查看命令。")
    reads: asyncio.Queue[_ReadResult] = asyncio.Queue()
    reader_closed = threading.Event()
    _start_reader(readline, reads, reader_closed)
    display = asyncio.create_task(_display_messages(console, output), name="aurora-console-output")
    read_task: asyncio.Task[_ReadResult] | None = None
    stop_task: asyncio.Task[bool] | None = None
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
                control.request_shutdown()
                return
            raw = (result.text or "").strip()
            if not raw:
                continue
            routed = await control.route_input(
                RuntimeInput(
                    text=raw,
                    origin=InputOrigin.CONSOLE,
                    session_id="local:console",
                    source_app="platform.console",
                    source_instance="default",
                    reply_capability="org.aurora.console.send_message",
                )
            )
            if routed.text is not None:
                output(routed.text)
            if routed.control is CommandControl.SHUTDOWN_PROCESS:
                control.request_shutdown()
                return
    finally:
        reader_closed.set()
        await _cancel_tasks(read_task, stop_task, display)
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


async def _display_messages(console: ConsolePlatform, output: Callable[[str], None]) -> None:
    while True:
        output(f"Bot> {await console.next_message()}")


async def _cancel_tasks(*tasks: asyncio.Task[Any] | None) -> None:
    active = [task for task in tasks if task is not None]
    for task in active:
        task.cancel()
    await asyncio.gather(*active, return_exceptions=True)
