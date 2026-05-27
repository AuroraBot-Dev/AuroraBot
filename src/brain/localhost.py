"""AuroraBot 本地控制 —— 提供控制台热重载与停机能力。

触发方式：开发者在控制台输入 ``~reload`` / ``~stop``。
"""

from __future__ import annotations

import asyncio
import importlib
import os
import signal
import sys
import threading
from types import ModuleType
from typing import Awaitable, Callable

from src.brain.runtime import (
    RuntimeState,
    restart_runtime_components,
    shutdown_runtime,
    stop_runtime_components,
)
from src.utils.log_utils import get_logger

logger = get_logger("Localhost")

RELOAD_COMMANDS = frozenset({"~reload", "/reload"})
STOP_COMMANDS = frozenset({"~stop", "/stop"})
DEVELOPER_COMMANDS = RELOAD_COMMANDS | STOP_COMMANDS

_MODULES_TO_RELOAD: list[str] = [
    "src.platform.app_config",
    "src.platform.app_discovery",
    "src.utils.json_utils",
    "src.brain.ai.llm_gate",
    "src.brain.prompts",
    "src.brain.kernel.base",
    "src.brain.kernel.circuit",
    "src.brain.kernel.state_store",
    "src.brain.nodes.agents.polaris_agent",
    "src.brain.nodes.agents",
    "src.brain.nodes.event_bridge",
    "src.brain.nodes",
    "src.brain.kernel.node_factory",
]

_MODULES_TO_SKIP_RELOAD: dict[str, str] = {
    "src.config": "该模块由 NoneBot 插件系统管理",
    "src.main": "该模块由 NoneBot 插件系统管理",
}


class HotReloadError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        runtime: RuntimeState,
    ) -> None:
        super().__init__(message)
        self.runtime = runtime


def _reload_module(name: str) -> None:
    try:
        module = importlib.import_module(name)
        skip_reason = _should_skip_reload(name, module)
        if skip_reason is not None:
            logger.info(f"跳过模块重载 {name}: {skip_reason}")
            return
        importlib.reload(module)
        logger.info(f"已重载模块 {name}")
    except Exception:
        logger.exception(f"重载模块 {name} 失败")
        raise


def _should_skip_reload(name: str, module: ModuleType) -> str | None:
    if name in _MODULES_TO_SKIP_RELOAD:
        return _MODULES_TO_SKIP_RELOAD[name]

    spec = getattr(module, "__spec__", None)
    loader = getattr(spec, "loader", None)
    if loader is None:
        return None

    loader_module = getattr(loader.__class__, "__module__", "")
    if loader_module.startswith("nonebot.plugin"):
        return "该模块由 NoneBot 插件加载器管理"
    return None


def _reload_modules() -> None:
    importlib.invalidate_caches()
    for name in _MODULES_TO_RELOAD:
        _reload_module(name)


def _reload_package_modules(package_name: str) -> None:
    names = [
        name
        for name in sys.modules
        if name == package_name or name.startswith(f"{package_name}.")
    ]
    for name in sorted(names, key=lambda item: (item.count("."), item), reverse=True):
        _reload_module(name)


async def reload_brain(
    *,
    runtime: RuntimeState,
) -> RuntimeState:
    """热重载脑回路：停止 → 重载模块 → 重建 → 重启。"""
    logger.info("热重载开始 — 冻结运行时...")
    previous_apps = [
        app
        for package in runtime.host.list_apps()
        if (app := runtime.host.get_app(package)) is not None
    ]
    previous_had_app_loop = runtime.app_task is not None
    previous_had_bridge = runtime.bridge_task is not None
    apps_replaced = False

    try:
        await stop_runtime_components(runtime)

        _reload_modules()

        from src.brain.runtime import start_runtime_components
        from src.platform.app_config import (
            app_startup,
            enabled_app_names,
            load_apps_config,
        )
        from src.platform.app_discovery import discover_apps, instantiate_app

        apps_config = load_apps_config()
        discovered = discover_apps()
        enabled_names = [
            name for name in enabled_app_names(apps_config) if name in discovered
        ]
        for app_name in enabled_names:
            _reload_package_modules(f"apps.{app_name}")

        new_apps = [
            instantiate_app(app_name, app_startup(apps_config, app_name))
            for app_name in enabled_names
        ]
        await runtime.host.replace_apps(new_apps)
        apps_replaced = True

        runtime.circuit = None
        runtime.app_task = None
        runtime.bridge_task = None
        await start_runtime_components(runtime)
    except Exception as exc:
        logger.exception("热重载失败，准备回滚到旧运行时")
        try:
            if apps_replaced:
                await runtime.host.replace_apps(previous_apps)
            runtime.app_task = None
            runtime.bridge_task = None
            await restart_runtime_components(
                runtime,
                start_app_loop=previous_had_app_loop,
                start_bridge=previous_had_bridge,
            )
        except Exception:
            logger.exception("热重载回滚失败，运行时可能处于部分可用状态")
        raise HotReloadError(
            "热重载失败，已尝试回滚旧运行时",
            runtime=runtime,
        ) from exc

    logger.info("热重载完成")
    return runtime


async def stop_process(*, runtime: RuntimeState) -> None:
    logger.info("收到停止请求，准备关闭当前进程")
    await shutdown_runtime(runtime)
    sys.stdout.flush()
    sys.stderr.flush()
    _request_process_exit()


async def run_console_control_loop(
    dispatch_command: Callable[[str], Awaitable[None]],
    *,
    readline: Callable[[], str] | None = None,
    idle_delay: float = 0.5,
) -> None:
    read_line = readline or sys.stdin.readline
    loop = asyncio.get_running_loop()
    input_queue: asyncio.Queue[str] = asyncio.Queue()
    stop_event = threading.Event()

    def _reader() -> None:
        while not stop_event.is_set():
            try:
                line = read_line()
            except Exception:
                logger.exception("控制台输入读取失败")
                break

            if line == "":
                if stop_event.wait(idle_delay):
                    break
                continue

            try:
                loop.call_soon_threadsafe(input_queue.put_nowait, line)
            except RuntimeError:
                break

    reader_thread = threading.Thread(
        target=_reader,
        name="console-control-reader",
        daemon=True,
    )
    reader_thread.start()
    logger.info(
        f"控制台命令监听已启动，支持命令: [{', '.join(sorted(DEVELOPER_COMMANDS))}]"
    )
    try:
        while True:
            line = await input_queue.get()
            command = line.strip()
            if not command:
                continue

            await dispatch_command(command)
    except asyncio.CancelledError:
        stop_event.set()
        logger.info("控制台命令监听已停止")
        raise


def _request_process_exit() -> None:
    try:
        signal.raise_signal(signal.SIGINT)
    except AttributeError:
        os.kill(os.getpid(), signal.SIGINT)
