from __future__ import annotations
import asyncio
import contextlib

from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import MessageEvent

from src.brain.hotreload import reload_brain
from src.brain.kernel.circuit import Circuit
from src.brain.kernel.node_factory import build_circuit
from src.brain.nodes import run_event_bridge
from src.config import Config
from src.platform.app_config import app_startup, load_apps_config
from src.platform.app_discovery import instantiate_app
from src.platform.application_host import app_host
from src.platform.loop import run_app_loop
from src.utils.log_utils import get_logger

logger = get_logger("Main")
driver = get_driver()
_app_task: asyncio.Task[None] | None = None
_bridge_task: asyncio.Task[None] | None = None
_circuit: Circuit | None = None
_stop_event: asyncio.Event | None = None


@driver.on_startup
async def startup_agent() -> None:
    global _app_task, _bridge_task, _circuit, _stop_event

    Config.ensure_dirs()
    apps_config = load_apps_config()

    for app_name, spec in apps_config.items():
        if not bool(spec.get("enabled", False)):
            continue
        await app_host.register(
            instantiate_app(app_name, app_startup(apps_config, app_name))
        )

    _stop_event = asyncio.Event()

    if Config.RUN_MODE in ["app", "application", "prod"]:
        # 启动应用循环
        _app_task = asyncio.create_task(
            run_app_loop(app_host, _stop_event, Config.APP_FRAME_INTERVAL)
        )

    if Config.RUN_MODE in ["agent", "core", "prod"]:
        # 启动图结构电路（替代旧 run_agent_loop 轮询调度）
        _circuit = build_circuit(app_host)
        await _circuit.start()  # 先启动电路，确保 _bus 就绪
        _bridge_task = asyncio.create_task(
            run_event_bridge(
                app_host,
                _circuit,
                _stop_event,
                interval=Config.HEARTBEAT_INTERVAL,
            )
        )

    _register_hotreload()


def _register_hotreload() -> None:
    developer_qq = Config.DEVELOPER_QQ.strip()

    @on_message(priority=99, block=False).handle()
    async def _maybe_reload(event: MessageEvent) -> None:
        global _circuit, _bridge_task
        if str(event.user_id) != developer_qq:
            return
        raw = (event.raw_message or "").strip()
        if raw not in ("~reload", "热重载"):
            return

        logger.info("收到热重载指令 (user=%s)", developer_qq)
        current_circuit = _circuit
        current_bridge = _bridge_task
        try:
            new_circuit, new_bridge = await reload_brain(
                host=app_host,
                circuit=current_circuit,
                bridge_task=current_bridge,
                stop_event=_stop_event,
            )
        except Exception:
            logger.exception("热重载失败")
            return

        _circuit = new_circuit
        _bridge_task = new_bridge


@driver.on_shutdown
async def shutdown_agent() -> None:
    global _app_task, _bridge_task, _circuit

    if _stop_event is not None:
        _stop_event.set()

    # 先关闭事件桥接
    if _bridge_task is not None:
        _bridge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _bridge_task
    _bridge_task = None

    # 再关闭图结构电路
    if _circuit is not None:
        await _circuit.stop()
    _circuit = None

    # 最后关闭应用循环
    if _app_task is not None:
        _app_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _app_task
    _app_task = None

    # 等待结束
    await app_host.stop_all()
    logger.info("所有循环已中止")
