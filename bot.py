"""AuroraBot Core 入口。

启动 Brain 运行时 + Platform（MCP Host）+ localhost 控制台。

Usage::

    uv run python bot.py
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import TYPE_CHECKING, Any

from src.brain.localhost import handle_control_command, run_console_control_loop
from src.brain.runtime import RuntimeState, shutdown_runtime, start_runtime
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import FrameType

logger = get_logger("AuroraCore")

_runtime: RuntimeState | None = None
_reload_lock = asyncio.Lock()


async def _handle_control_command(raw: str) -> None:
    global _runtime  # noqa: PLW0603
    _runtime = await handle_control_command(raw, runtime=_runtime, lock=_reload_lock)


def _install_stop_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    stop_event: asyncio.Event,
) -> Callable[[], None]:
    """安装停止信号处理，并在 Windows Proactor loop 上回退到 ``signal.signal``。"""
    loop_signals: list[signal.Signals] = []
    fallback_handlers: dict[signal.Signals, Any] = {}

    def _signal_handler() -> None:
        logger.info("收到停止信号")
        stop_event.set()

    def _fallback_handler(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(_signal_handler)

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, _signal_handler)
            loop_signals.append(signum)
        except (NotImplementedError, RuntimeError):
            fallback_handlers[signum] = signal.signal(signum, _fallback_handler)

    def _remove_handlers() -> None:
        for signum in loop_signals:
            loop.remove_signal_handler(signum)
        for signum, handler in fallback_handlers.items():
            signal.signal(signum, handler)

    return _remove_handlers


async def main() -> None:
    global _runtime  # noqa: PLW0603

    logger.info("AuroraBot Core 启动中...")
    console_task: asyncio.Task[None] | None = None
    stop_event = asyncio.Event()
    remove_signal_handlers = _install_stop_signal_handlers(asyncio.get_running_loop(), stop_event)

    try:
        _runtime = await start_runtime()
        console_task = asyncio.create_task(
            run_console_control_loop(_handle_control_command),
            name="console-control-loop",
        )
        await stop_event.wait()
    finally:
        remove_signal_handlers()

        if console_task is not None:
            console_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await console_task

        if _runtime is not None:
            await shutdown_runtime(_runtime)
            _runtime = None

        logger.info("AuroraBot Core 已关闭")


if __name__ == "__main__":
    asyncio.run(main())
