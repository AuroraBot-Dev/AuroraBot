"""管理进程级运行入口与启动/关闭生命周期。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aurora.configuration.platforms import PLATFORMS_CONFIG, PlatformConfig
from aurora.runtime.assembly import assemble_runtime_managed
from aurora.runtime.support import (
    InstalledSignal,
    configure_project_logging,
    install_stop_handlers,
    restore_stop_handlers,
)
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool
    from src.kernel import ContributionBinding, InstanceBinding, ManagedAssembly
    from src.runtime import AuroraRuntime

_logger = get_logger(__name__)

_CONSOLE_PLATFORM_ID = "builtin.console"


async def run_project(
    config: AuroraConfig,
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
    configure_project_logging(config)
    _logger.info("Aurora runtime 启动 headless={}", headless)
    stop = stop_event or asyncio.Event()
    try:
        runtime, lifecycle = await assemble_runtime_managed(
            config,
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

    installed = ()
    try:
        console_platform = _platform(config, _CONSOLE_PLATFORM_ID)
        installed = install_stop_handlers(stop) if stop_event is None else ()
        if not headless and console_platform.enabled:
            await runtime.console.run(runtime.terminal, stop_event=stop, readline=readline, output=output)
        else:
            await stop.wait()
    finally:
        await _shutdown_project(installed, lifecycle)
    return runtime


async def _shutdown_project(
    installed: tuple[InstalledSignal, ...],
    lifecycle: ManagedAssembly,
) -> None:
    _logger.info("Aurora runtime 开始关闭")
    try:
        restore_stop_handlers(installed)
    finally:
        await lifecycle.close()
    _logger.info("Aurora runtime 已关闭")


def _platform(config: AuroraConfig, platform_id: str) -> PlatformConfig:
    for item in config.get(PLATFORMS_CONFIG).platforms:
        if item.id == platform_id:
            return item
    raise ValueError(f"平台尚未声明：{platform_id}")
