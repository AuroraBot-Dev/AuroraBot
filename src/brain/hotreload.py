"""AuroraBot 热重载 —— 保持 QQ/NoneBot 连接存活，仅重启脑回路。

触发方式：开发者在 QQ 发送 ``~reload`` 或 ``热重载``。
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from typing import TYPE_CHECKING

from src.brain.runtime import RuntimeState, restart_runtime_components, stop_runtime_components
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("HotReload")

_MODULES_TO_RELOAD = [
    "src.config",
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
        importlib.reload(module)
        logger.info("已重载模块 %s", name)
    except Exception:
        logger.exception("重载模块 %s 失败", name)
        raise


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
    """热重载脑回路：停止 → 重载模块 → 重建 → 重启。

    Parameters
    ----------
    runtime : RuntimeState
        当前运行时句柄集合。

    Returns
    -------
    RuntimeState
        新的运行时句柄集合。
    """
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

        # 1) 重载 Python 模块
        _reload_modules()

        from src.brain.runtime import start_runtime_components
        from src.config import Config
        from src.platform.app_config import (
            app_startup,
            enabled_app_names,
            load_apps_config,
        )
        from src.platform.app_discovery import discover_apps, instantiate_app

        # 4) 重载应用模块并替换宿主中的应用实例/命令绑定
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
