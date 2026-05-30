from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("AppLoop")


async def run_app_loop(
    host: ApplicationHost,
    stop_event: asyncio.Event,
    interval: float,
) -> None:
    logger.info("应用循环已启动")

    # 主调度
    while not stop_event.is_set():
        try:
            await host.tick()
        except Exception as exc:
            logger.exception(f"应用帧错误: {exc}")  # noqa: TRY401
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.05, interval))
        except TimeoutError:
            continue
