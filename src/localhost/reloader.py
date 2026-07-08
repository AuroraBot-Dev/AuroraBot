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
    from src.runtime import RuntimeState

logger = get_logger("Localhost")

_SELF_MODULE = __name__
_RELOAD_FIRST = ("src.config", "src.utils.log_utils")


class HotReloadError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        runtime: RuntimeState | None,
    ) -> None:
        super().__init__(message)
        self.runtime = runtime


def _reload_module(name: str) -> None:
    try:
        module = importlib.import_module(name)
        importlib.reload(module)
        logger.info(f"已重载模块 {name}")
    except Exception:
        logger.exception(f"重载模块 {name} 失败")
        raise


def _project_module_names() -> list[str]:
    loaded_modules = {
        name
        for name, module in sys.modules.items()
        if (name == "src" or name.startswith("src.")) and getattr(module, "__spec__", None) is not None
    }
    names = [name for name in loaded_modules if name not in _RELOAD_FIRST and name != _SELF_MODULE]
    names.sort(key=lambda name: (-name.count("."), name))

    ordered = [name for name in _RELOAD_FIRST if name in loaded_modules]
    ordered.extend(names)
    if _SELF_MODULE in loaded_modules:
        ordered.append(_SELF_MODULE)
    return ordered


def _reload_modules() -> None:
    importlib.invalidate_caches()
    names = _project_module_names()
    for name in names:
        _reload_module(name)
    logger.info("项目模块热重载完成: %d 个模块", len(names))


async def reload_runtime(*, runtime: RuntimeState) -> RuntimeState:
    """热重载完整运行时。

    Args:
        runtime: 当前运行时状态。

    Returns:
        新的运行时状态。
    """
    logger.info("热重载开始 — 校验配置并重启 MCP 运行时...")

    try:
        from src.config import reload_env

        reload_env()
        from src.platform.mcp.discovery import discover_mcp_servers

        discover_mcp_servers()
    except Exception as exc:
        raise HotReloadError("热重载预检失败，旧运行时仍在运行", runtime=runtime) from exc

    from src.runtime import shutdown_runtime

    try:
        await shutdown_runtime(runtime)
    except Exception as exc:
        raise HotReloadError("热重载关闭旧运行时失败", runtime=runtime) from exc

    try:
        _reload_modules()

        from src.runtime import start_runtime

        new_runtime = await start_runtime()
    except Exception as exc:
        raise HotReloadError("热重载启动新运行时失败，当前进程没有可用运行时", runtime=None) from exc

    logger.info("热重载完成")
    return new_runtime


async def reload_brain(*, runtime: RuntimeState) -> RuntimeState:
    """Backward-compatible alias for full runtime hot reload."""
    return await reload_runtime(runtime=runtime)


def _request_process_exit() -> None:
    """请求进程退出。"""
    with contextlib.suppress(OSError, ValueError):
        signal.raise_signal(signal.SIGINT)
    os._exit(0)


async def stop_process(*, runtime: RuntimeState) -> None:
    """停止运行时并退出进程。"""
    from src.runtime import shutdown_runtime

    logger.info("收到停止请求，准备关闭当前进程")
    await shutdown_runtime(runtime)
    sys.stdout.flush()
    sys.stderr.flush()
    _request_process_exit()
