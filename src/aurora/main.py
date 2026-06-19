"""AuroraBot Core 独立入口。

启动 Brain 运行时 + Platform（MCP Host）+ localhost 控制台。
不依赖 NoneBot 框架。

Usage::

    uv run python -m src.aurora.main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from src.brain.localhost import handle_control_command, run_console_control_loop
from src.brain.runtime import RuntimeState, shutdown_runtime, start_runtime
from src.utils.log_utils import get_logger

logger = get_logger("AuroraCore")

_runtime: RuntimeState | None = None
_reload_lock = asyncio.Lock()


async def _handle_control_command(raw: str) -> None:
    global _runtime  # noqa: PLW0603
    _runtime = await handle_control_command(raw, runtime=_runtime, lock=_reload_lock)


async def main() -> None:
    global _runtime  # noqa: PLW0603

    logger.info("AuroraBot Core 启动中...")

    _runtime = await start_runtime()

    console_task = asyncio.create_task(
        run_console_control_loop(_handle_control_command),
        name="console-control-loop",
    )

    # 信号处理
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("收到停止信号")
        stop_event.set()

    if hasattr(signal, "SIGINT"):
        loop.add_signal_handler(signal.SIGINT, _signal_handler)  # type: ignore[arg-type]
    if hasattr(signal, "SIGTERM"):
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)  # type: ignore[arg-type]

    await stop_event.wait()

    # 关闭
    console_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await console_task

    if _runtime is not None:
        await shutdown_runtime(_runtime)
        _runtime = None

    logger.info("AuroraBot Core 已关闭")


if __name__ == "__main__":
    asyncio.run(main())
