"""通过测试控制文件在真实 CLI 进程内触发 Ctrl+C 退出路径。"""

import asyncio
import os
import signal
from pathlib import Path

from aurora_cli import main as entry

run_cli = entry.run_cli


async def interrupt_when_requested():
    path = Path(os.environ["AURORA_TEST_STOP_FILE"])
    while not path.exists():
        await asyncio.sleep(0.02)
    signal.raise_signal(signal.SIGINT)


async def run():
    interrupter = asyncio.create_task(interrupt_when_requested())
    try:
        return await run_cli()
    finally:
        interrupter.cancel()
        await asyncio.gather(interrupter, return_exceptions=True)


entry.run_cli = run
raise SystemExit(entry.main())
