"""把进程终止信号转为异步停止事件，并可恢复原处理器。"""

from __future__ import annotations

import signal
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable
    from types import FrameType

type SignalHandler = Callable[[int, FrameType | None], object] | int | None


@dataclass(frozen=True, slots=True)
class InstalledSignal:
    """记录一个可恢复的进程信号处理器。"""

    candidate: signal.Signals
    previous: SignalHandler


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
        signal.signal(item.candidate, item.previous)
