"""提供运行时入口使用的进程级辅助函数。"""

from __future__ import annotations

import signal
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.configuration.runtime import RUNTIME_CONFIG
from aurora.configuration.storage import STORAGE_CONFIG
from src.utils import configure_console_logging, configure_logging

if TYPE_CHECKING:
    import asyncio

    from aurora.config import AuroraConfig


@dataclass(frozen=True, slots=True)
class InstalledSignal:
    """记录一个可恢复的进程信号处理器。"""

    candidate: signal.Signals
    previous: object


def configure_project_logging(config: AuroraConfig) -> None:
    """在其他运行时效果前应用项目日志配置。"""
    runtime = config.get(RUNTIME_CONFIG)
    logfile = config.project_root / config.get(STORAGE_CONFIG).resolve("logs") / "aurora.log"
    configure_console_logging(enabled=True, level=runtime.log_level)
    configure_logging(runtime.log_level, logfile)


def install_stop_handlers(stop: asyncio.Event) -> tuple[InstalledSignal, ...]:
    """安装信号处理器，使进程终止信号转为异步停止事件。"""
    installed: list[InstalledSignal] = []
    try:
        for candidate in (signal.SIGINT, signal.SIGTERM):
            previous = signal.getsignal(candidate)

            def handle_signal(_signum: int, _frame: object, *, event: asyncio.Event = stop) -> None:
                event.set()

            signal.signal(candidate, handle_signal)
            installed.append(InstalledSignal(candidate, previous))
    except BaseException:
        restore_stop_handlers(tuple(installed))
        raise
    return tuple(installed)


def restore_stop_handlers(installed: tuple[InstalledSignal, ...]) -> None:
    """恢复入口启动前的进程信号处理器。"""
    for item in installed:
        signal.signal(item.candidate, item.previous)  # type: ignore[arg-type]
