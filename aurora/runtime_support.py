"""运行时入口使用的进程级辅助函数。"""

from __future__ import annotations

import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio


@dataclass(frozen=True, slots=True)
class InstalledSignal:
    """记录一个可恢复的进程信号处理器。"""

    candidate: signal.Signals
    previous: object


def install_stop_handlers(stop: asyncio.Event) -> tuple[InstalledSignal, ...]:
    """安装把进程终止信号转为异步停止事件的处理器。"""
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


def parse_event_time(value: str) -> datetime:
    """解析带时区的 ISO 8601 事件时间并归一化为 UTC。"""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("occurred_at 必须是 ISO 8601 时间") from error
    if parsed.tzinfo is None:
        raise ValueError("occurred_at 必须包含时区")
    return parsed.astimezone(UTC)
