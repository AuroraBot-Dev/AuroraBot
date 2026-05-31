from __future__ import annotations

import contextlib
import importlib
import os
import signal
import sys
from typing import TYPE_CHECKING

from src.brain.runtime import (
    restart_runtime_components,
    shutdown_runtime,
    stop_runtime_components,
)
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from types import ModuleType

    from src.brain.runtime import RuntimeState

logger = get_logger("Localhost")

_SELF_MODULE = "src.brain.localhost"

_MODULES_TO_RELOAD: list[str] = [
    "src.platform.app_config",
    "src.platform.app_discovery",
    "src.utils.json_utils",
    "src.brain.ai.gateway",
    "src.brain.prompts",
    "src.brain.kernel.base",
    "src.brain.kernel.circuit",
    "src.brain.kernel.state_store",
    "src.brain.nodes.agents.polaris_agent",
    "src.brain.nodes.agents",
    "src.brain.nodes.event_bridge",
    "src.brain.nodes",
    "src.brain.kernel.node_factory",
    "src.brain.runtime",
    _SELF_MODULE,
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


def _reload_modules() -> None:
    importlib.invalidate_caches()
    names = [name for name in _MODULES_TO_RELOAD if name != _SELF_MODULE]
    if _SELF_MODULE in _MODULES_TO_RELOAD:
        names.append(_SELF_MODULE)
    for name in names:
        _reload_module(name)


def _reload_package_modules(package_name: str) -> None:
    names = [name for name in sys.modules if name == package_name or name.startswith(f"{package_name}.")]
    for name in sorted(names, key=lambda item: (item.count("."), item), reverse=True):
        _reload_module(name)


async def reload_brain(*, runtime: RuntimeState) -> RuntimeState:
    logger.info("热重载开始 — 冻结运行时...")
    previous_apps = [app for package in runtime.host.list_apps() if (app := runtime.host.get_app(package)) is not None]
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
        enabled_names = [name for name in enabled_app_names(apps_config) if name in discovered]
        for app_name in enabled_names:
            _reload_package_modules(f"apps.{app_name}")

        new_apps = [instantiate_app(app_name, app_startup(apps_config, app_name)) for app_name in enabled_names]
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


def _request_process_exit() -> None:
    """请求进程退出。

    先尝试 SIGINT（Unix 下由 NoneBot driver 捕获后优雅关闭），
    随后用 ``os._exit(0)`` 硬退出作为兜底（Windows + asyncio 下 SIGINT 不可靠）。
    """
    with contextlib.suppress(OSError, ValueError):
        signal.raise_signal(signal.SIGINT)
    # 硬兜底：SIGINT 在 Windows asyncio 事件循环中常被吞掉，
    # shutdown_runtime 已完成所有清理，直接 _exit 是安全的。
    os._exit(0)


async def stop_process(*, runtime: RuntimeState) -> None:
    logger.info("收到停止请求，准备关闭当前进程")
    await shutdown_runtime(runtime)
    sys.stdout.flush()
    sys.stderr.flush()
    _request_process_exit()
