"""根入口的信号处理测试。"""

from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING

import bot

if TYPE_CHECKING:
    import pytest


class _NoSignalLoop:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def add_signal_handler(self, _signum: signal.Signals, _callback: object) -> None:
        raise NotImplementedError

    def call_soon_threadsafe(self, callback: object) -> None:
        self.callbacks.append(callback)
        callback()  # type: ignore[operator]


def test_stop_signal_handler_falls_back_when_event_loop_lacks_signal_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: dict[signal.Signals, object] = {}

    def fake_signal(signum: signal.Signals, handler: object) -> object:
        previous = installed.get(signum, signal.SIG_DFL)
        installed[signum] = handler
        return previous

    monkeypatch.setattr(bot.signal, "signal", fake_signal)
    stop_event = asyncio.Event()
    remove_handlers = bot._install_stop_signal_handlers(_NoSignalLoop(), stop_event)  # type: ignore[arg-type]

    installed[signal.SIGINT](signal.SIGINT, None)  # type: ignore[operator]

    assert stop_event.is_set()
    remove_handlers()
