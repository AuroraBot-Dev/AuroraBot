"""终端分派与控制的最小契约。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class TerminalControl(StrEnum):
    NONE = "none"
    CLEAR = "clear"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True, slots=True)
class TerminalResponse:
    text: str | None = None
    control: TerminalControl = TerminalControl.NONE
    is_error: bool = False


class TerminalDispatcher(Protocol):
    async def dispatch_terminal(self, text: str) -> TerminalResponse: ...
