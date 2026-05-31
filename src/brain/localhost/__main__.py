from __future__ import annotations

import asyncio

from src.brain.localhost.shell import handle_control_command, run_console_control_loop
from src.brain.runtime import start_runtime
from src.platform.application_host import app_host
from src.utils.log_utils import get_logger

logger = get_logger("Localhost")


async def main() -> None:
    runtime = await start_runtime(app_host)
    _reload_lock = asyncio.Lock()

    async def dispatch(command: str) -> None:
        nonlocal runtime
        result = await handle_control_command(command, runtime=runtime, lock=_reload_lock)
        if result is not None:
            runtime = result

    await run_console_control_loop(dispatch_command=dispatch)


if __name__ == "__main__":
    asyncio.run(main())
