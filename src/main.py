from __future__ import annotations

import asyncio
import contextlib

from nonebot import get_driver

from src.brain.localhost import handle_control_command, run_console_control_loop
from src.brain.runtime import RuntimeState, shutdown_runtime, start_runtime
from src.platform.application_host import app_host
from src.utils.log_utils import get_logger

logger = get_logger("Main")
driver = get_driver()
_runtime: RuntimeState | None = None
_console_task: asyncio.Task[None] | None = None
_reload_lock = asyncio.Lock()


@driver.on_startup
async def startup_agent() -> None:
    global _runtime, _console_task  # noqa: PLW0603

    _runtime = await start_runtime(app_host)
    _console_task = asyncio.create_task(
        run_console_control_loop(_handle_control_command),
        name="console-control-loop",
    )


async def _handle_control_command(raw: str) -> None:
    global _runtime  # noqa: PLW0603
    _runtime = await handle_control_command(raw, runtime=_runtime, lock=_reload_lock)


@driver.on_shutdown
async def shutdown_agent() -> None:
    global _runtime, _console_task  # noqa: PLW0603

    if _console_task is not None:
        _console_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _console_task
        _console_task = None

    if _runtime is None:
        return

    await shutdown_runtime(_runtime)
    _runtime = None
