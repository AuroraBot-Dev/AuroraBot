"""Runtime 热重载与进程管理。

提供 ``/reload`` 和 ``/stop`` 控制台命令的实现。
"""

from __future__ import annotations

import contextlib
import importlib
import os
import signal
import sys
from typing import TYPE_CHECKING

from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from types import ModuleType

    from src.brain.runtime import RuntimeState

logger = get_logger("Localhost")

_SELF_MODULE = "src.brain.localhost"

_MODULES_TO_RELOAD: list[str] = [
    "src.utils.json_utils",
    "src.brain.ai.gateway",
    "src.brain.prompts",
    "src.brain.kernel.base",
    "src.brain.kernel.circuit",
    "src.brain.kernel.state_store",
    "src.brain.nodes.agents",
    "src.brain.nodes.event_bridge",
    "src.brain.nodes",
    "src.brain.kernel.node_factory",
    "src.brain.runtime",
    "src.platform.mcp_kit.client_manager",
    "src.platform.mcp_kit.server_kit",
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


async def reload_brain(*, runtime: RuntimeState) -> RuntimeState:
    """热重载运行时：保留 MCP 连接，重建 Circuit。

    Args:
        runtime: 当前运行时状态。

    Returns:
        新的运行时状态。
    """
    logger.info("热重载开始 — 停止 Circuit...")

    # 停止 Circuit（保留 MCP 连接）
    if runtime.circuit is not None and runtime.circuit.is_running:
        await runtime.circuit.stop()

    # 取消后台任务（保留 MCP Client/Server）
    import asyncio

    for task in runtime.tasks:
        task.cancel()
    for task in runtime.tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    runtime.tasks.clear()

    # 重载模块
    _reload_modules()

    # 重建 Circuit
    from src.brain.kernel.node_factory import build_circuit
    from src.brain.nodes import run_mcp_event_bridge

    runtime.circuit = build_circuit(client_manager=runtime.client_manager)
    await runtime.circuit.start()

    bridge_task = asyncio.create_task(
        run_mcp_event_bridge(runtime.client_manager, runtime.circuit, runtime.stop_event),
        name="mcp-event-bridge",
    )
    runtime.tasks.append(bridge_task)

    logger.info("热重载完成")
    return runtime


def _request_process_exit() -> None:
    """请求进程退出。"""
    with contextlib.suppress(OSError, ValueError):
        signal.raise_signal(signal.SIGINT)
    os._exit(0)


async def stop_process(*, runtime: RuntimeState) -> None:
    """停止运行时并退出进程。"""
    from src.brain.runtime import shutdown_runtime

    logger.info("收到停止请求，准备关闭当前进程")
    await shutdown_runtime(runtime)
    sys.stdout.flush()
    sys.stderr.flush()
    _request_process_exit()
