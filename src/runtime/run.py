"""进程运行编排：激活模块生命周期并让 Console 或停止事件拥有前台。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.runtime.assembly import compose_runtime
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from src.contracts import Model, Settings, Tool
    from src.kernel import ContributionBinding, InstanceBinding
    from src.runtime.core import AuroraRuntime

_logger = get_logger(__name__)


async def run_runtime(
    settings: Settings,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    headless: bool = False,
    stop_event: asyncio.Event | None = None,
    readline: Callable[[str], str] | None = None,
    output: Callable[[str], None] = print,
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> AuroraRuntime:
    """通过统一模块生命周期组合运行时，并让 Console 或停止事件拥有进程前台。"""
    _logger.info("Aurora runtime 启动 headless={}", headless)
    stop = stop_event or asyncio.Event()
    try:
        runtime, lifecycle = await compose_runtime(
            settings,
            model,
            tools,
            output=output,
            instances=instances,
            contributions=contributions,
        )
        await lifecycle.activate(stop)
        _logger.info("Aurora runtime 装配完成")
    except BaseException as error:
        _logger.error("Aurora runtime 启动失败 error_type={}", type(error).__name__)
        raise
    try:
        if not headless:
            await runtime.console.run(runtime.terminal, stop_event=stop, readline=readline, output=output)
        else:
            await stop.wait()
    finally:
        _logger.info("Aurora runtime 开始关闭")
        await lifecycle.close()
        _logger.info("Aurora runtime 已关闭")
    return runtime
