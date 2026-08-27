"""进程级运行入口与启动/关闭生命周期。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING

from aurora.composition.mcp import build_mcp_specs
from aurora.composition.world import build_world
from aurora.configuration.platforms import PLATFORMS_CONFIG
from aurora.configuration.storage import STORAGE_CONFIG
from aurora.runtime.assembly import assemble_runtime
from aurora.runtime.panel import PanelRuntime, close_panel, run_panel
from aurora.runtime.support import (
    InstalledSignal,
    configure_project_logging,
    install_stop_handlers,
    restore_stop_handlers,
)
from src.mcp import McpRuntime, prepare_mcp
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora.config import AuroraConfig
    from aurora.runtime.core import AuroraRuntime
    from src.contracts import Model, Tool, WorldJournal
    from src.mcp import McpClientFactory

_logger = get_logger(__name__)


async def run_project(
    config: AuroraConfig,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    headless: bool = False,
    stop_event: asyncio.Event | None = None,
    readline: Callable[[str], str] | None = None,
    output: Callable[[str], None] = print,
    mcp_factory: McpClientFactory | None = None,
) -> AuroraRuntime:
    """先冻结 MCP 工具目录，再组合运行时并让 Console 或停止事件拥有进程前台。"""
    configure_project_logging(config)
    _logger.info("Aurora runtime 启动 headless=%s", headless)
    world = build_world(config)
    mcp: McpRuntime | None = None
    try:
        await world.initialize()
        platform = config.get(PLATFORMS_CONFIG).mcp
        mcp = await prepare_mcp(
            build_mcp_specs(config),
            platform_enabled=platform.enabled,
            world=world,
            factory=mcp_factory,
        )
        _logger.info("MCP 工具目录已冻结 app_count=%d tool_count=%d", len(mcp.snapshot().apps), len(mcp.tools))
        runtime = assemble_runtime(config, model, tools, world=world, mcp=mcp, output=output)
        await _activate_runtime(runtime, mcp)
        _logger.info("Aurora runtime 装配完成")
    except BaseException as error:
        _logger.error("Aurora runtime 启动失败 error_type=%s", type(error).__name__)
        await _close_failed_startup(mcp, world)
        raise

    stop = stop_event or asyncio.Event()
    cadence_task: asyncio.Task[None] | None = None
    panel: PanelRuntime | None = None
    installed = ()
    try:
        runtime.bind_stop_requester(stop.set)
        panel = await run_panel(
            runtime.root.panel,
            runtime.ops,
            storage=config.get(STORAGE_CONFIG),
            project_root=config.project_root,
            profile=runtime.root.profile,
        )
        if runtime.cadence.enabled:
            cadence_task = asyncio.create_task(runtime.cadence.run(stop), name="aurora-cadence")
        installed = install_stop_handlers(stop) if stop_event is None else ()
        if not headless and runtime.root.console_enabled:
            await runtime.console.run(runtime, stop_event=stop, readline=readline, output=output)
        else:
            await stop.wait()
    finally:
        await _shutdown_project(runtime, panel, cadence_task, installed, mcp, world)
    return runtime


async def _close_failed_startup(mcp: McpRuntime | None, world: WorldJournal) -> None:
    if mcp is not None:
        with suppress(Exception):
            await mcp.close()
    with suppress(Exception):
        await world.close()


async def _shutdown_project(
    runtime: AuroraRuntime,
    panel: PanelRuntime | None,
    cadence_task: asyncio.Task[None] | None,
    installed: tuple[InstalledSignal, ...],
    mcp: McpRuntime,
    world: WorldJournal,
) -> None:
    _logger.info("Aurora runtime 开始关闭")
    runtime.bind_stop_requester(None)
    try:
        restore_stop_handlers(installed)
    finally:
        await close_panel(panel)
        if cadence_task is not None:
            cadence_task.cancel()
            await asyncio.gather(cadence_task, return_exceptions=True)
        try:
            await mcp.close()
        finally:
            await world.close()
    _logger.info("Aurora runtime 已关闭")


async def _activate_runtime(runtime: AuroraRuntime, mcp: McpRuntime) -> None:
    """先固定 Cadence cursor，再放行 MCP 业务事件。"""
    if runtime.cadence.enabled:
        await runtime.cadence.initialize()
    await mcp.activate()
