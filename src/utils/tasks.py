"""异步回收期间隔离调用者取消，并保留取消结果。"""

from __future__ import annotations

import asyncio


async def wait_for_completion[T](future: asyncio.Future[T]) -> tuple[T, asyncio.CancelledError | None]:
    """等待已有任务完成，调用者的取消由宿主在回收完成后处理。"""
    interrupted: asyncio.CancelledError | None = None
    while True:
        try:
            return await asyncio.shield(future), interrupted
        except asyncio.CancelledError as error:
            if future.cancelled():
                raise
            if interrupted is None:
                interrupted = error
