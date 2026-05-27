from __future__ import annotations
import asyncio

from nonebot import get_driver

from src.brain.localhost import (
    DEVELOPER_COMMANDS,
    HotReloadError,
    RELOAD_COMMANDS,
    STOP_COMMANDS,
    reload_brain,
    run_console_control_loop,
    stop_process,
)
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
    global _runtime, _console_task

    _runtime = await start_runtime(app_host)
    _console_task = asyncio.create_task(
        run_console_control_loop(_handle_control_command),
        name="console-control-loop",
    )


async def _handle_control_command(raw: str) -> None:
    global _runtime

    if raw not in DEVELOPER_COMMANDS:
        return
    if _runtime is None:
        logger.warning("控制命令已忽略: runtime 尚未初始化")
        return
    if _reload_lock.locked():
        logger.info("已有控制任务在执行，忽略重复指令")
        return

    logger.info(f"收到控制台指令: {raw}")
    async with _reload_lock:
        try:
            if raw in RELOAD_COMMANDS:
                _runtime = await reload_brain(runtime=_runtime)
                return
            if raw in STOP_COMMANDS:
                runtime = _runtime
                _runtime = None
                await stop_process(runtime=runtime)
                return
        except HotReloadError as exc:
            _runtime = exc.runtime
            logger.exception("热重载失败，已回滚旧运行时")
            return
        except Exception:
            logger.exception(f"控制台命令执行失败: {raw}")
            return


@driver.on_shutdown
async def shutdown_agent() -> None:
    global _runtime, _console_task

    if _console_task is not None:
        _console_task.cancel()
        try:
            await _console_task
        except asyncio.CancelledError:
            pass
        _console_task = None

    if _runtime is None:
        return

    await shutdown_runtime(_runtime)
    _runtime = None
