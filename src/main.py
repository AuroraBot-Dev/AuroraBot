from __future__ import annotations
import asyncio

from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import MessageEvent

from src.brain.hotreload import HotReloadError, reload_brain
from src.brain.runtime import RuntimeState, shutdown_runtime, start_runtime
from src.config import Config
from src.platform.application_host import app_host
from src.utils.log_utils import get_logger

logger = get_logger("Main")
driver = get_driver()
_runtime: RuntimeState | None = None
_reload_lock = asyncio.Lock()


@driver.on_startup
async def startup_agent() -> None:
    global _runtime

    _runtime = await start_runtime(app_host)

    _register_hotreload()


def _register_hotreload() -> None:
    developer_qq = Config.DEVELOPER_QQ.strip()

    @on_message(priority=99, block=False).handle()
    async def _maybe_reload(event: MessageEvent) -> None:
        global _runtime
        if str(event.user_id) != developer_qq:
            return
        raw = (event.raw_message or "").strip()
        if raw not in ("~reload", "热重载"):
            return

        if _runtime is None:
            logger.warning("热重载已忽略: runtime 尚未初始化")
            return
        if _reload_lock.locked():
            logger.info("已有热重载任务在执行，忽略重复指令")
            return

        logger.info("收到热重载指令 (user=%s)", developer_qq)
        async with _reload_lock:
            try:
                _runtime = await reload_brain(runtime=_runtime)
            except HotReloadError as exc:
                _runtime = exc.runtime
                logger.exception("热重载失败，已回滚旧运行时")
                return
            except Exception:
                logger.exception("热重载失败")
                return


@driver.on_shutdown
async def shutdown_agent() -> None:
    global _runtime

    if _runtime is None:
        return

    await shutdown_runtime(_runtime)
    _runtime = None
